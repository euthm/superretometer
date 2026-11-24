// Command superretometer serves the Cognitive Harness MCP API without Python.
package main

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/euthm/superretometer/go/internal/service"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

// Set revision with -ldflags '-X main.revision=<git commit>' when building.
var version = "0.10.0"
var revision = "development"

type stringList []string

func (s *stringList) String() string { return strings.Join(*s, ", ") }
func (s *stringList) Set(value string) error {
	if strings.TrimSpace(value) == "" {
		return errors.New("value must not be empty")
	}
	*s = append(*s, value)
	return nil
}

type config struct {
	Snapshot, State, Listen, TokenEnv           string
	ReadOnly, BehindProxy, Version, Healthcheck bool
	RepositoryRoots, AllowedOrigins             stringList
}

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := mainContext(ctx, os.Args[1:], os.Stdout, os.Stderr); err != nil {
		log.Print(err)
		os.Exit(1)
	}
}

func parseConfig(args []string, stderr io.Writer) (config, error) {
	cfg := config{}
	// Retain the Python CLI's optional mcp subcommand.
	if len(args) > 0 && args[0] == "mcp" {
		args = args[1:]
	}
	flags := flag.NewFlagSet("superretometer", flag.ContinueOnError)
	flags.SetOutput(stderr)
	flags.StringVar(&cfg.Snapshot, "snapshot", "", "JSON graph used to seed an empty state")
	flags.StringVar(&cfg.State, "state", "", "Durable JSON state file; omit for temporary in-memory stdio")
	flags.StringVar(&cfg.Listen, "listen", "", "HTTP listen address, e.g. 127.0.0.1:3010; omit for stdio")
	flags.BoolVar(&cfg.ReadOnly, "read-only", false, "Expose analysis tools only")
	flags.BoolVar(&cfg.BehindProxy, "behind-proxy", false, "An authenticated reverse proxy protects this HTTP listener")
	flags.StringVar(&cfg.TokenEnv, "auth-token-env", "SUPERRETOMETER_AUTH_TOKEN", "Environment variable containing an optional HTTP bearer token")
	flags.Var(&cfg.RepositoryRoots, "repository-root", "Trusted repository root for freshness checks; repeat for multiple roots")
	flags.Var(&cfg.AllowedOrigins, "allowed-origin", "Additional trusted HTTP origin; repeat for multiple origins")
	flags.BoolVar(&cfg.Version, "version", false, "Print version and source revision")
	flags.BoolVar(&cfg.Healthcheck, "healthcheck", false, "Check the local HTTP /healthz endpoint, then exit")
	flags.Usage = func() {
		fmt.Fprintln(stderr, "Usage: superretometer [mcp] [options]")
		fmt.Fprintln(stderr, "Stdio: superretometer mcp --state /path/state.json")
		fmt.Fprintln(stderr, "HTTP:  superretometer mcp --state /data/state.json --listen 127.0.0.1:3010")
		flags.PrintDefaults()
	}
	if err := flags.Parse(args); err != nil {
		return cfg, err
	}
	if flags.NArg() != 0 {
		return cfg, fmt.Errorf("unexpected argument %q; use superretometer [mcp] --state /path/state.json", flags.Arg(0))
	}
	return cfg, nil
}

func mainContext(ctx context.Context, args []string, stdout, stderr io.Writer) error {
	cfg, err := parseConfig(args, stderr)
	if errors.Is(err, flag.ErrHelp) {
		return nil
	}
	if err != nil {
		return err
	}
	if cfg.Version {
		_, err := fmt.Fprintf(stdout, "superretometer %s (%s)\n", version, revision)
		return err
	}
	if cfg.Healthcheck {
		return checkHealth(ctx, cfg.Listen)
	}
	token := os.Getenv(cfg.TokenEnv)
	if cfg.Listen != "" {
		if err := checkListenAddress(cfg.Listen); err != nil {
			return err
		}
		host, _, _ := net.SplitHostPort(cfg.Listen)
		ip := net.ParseIP(host)
		loopback := strings.EqualFold(host, "localhost") || (ip != nil && ip.IsLoopback())
		if !loopback && token == "" && !cfg.BehindProxy {
			return errors.New("non-loopback HTTP needs a bearer token in the configured environment variable, or --behind-proxy with an authenticated proxy")
		}
		if !cfg.ReadOnly && cfg.State == "" {
			return errors.New("writable HTTP needs --state /data/state.json so proposals survive restart; use --read-only for snapshot analysis")
		}
	}
	svc, err := service.Open(service.Options{SnapshotPath: cfg.Snapshot, StatePath: cfg.State, FreshnessRoots: cfg.RepositoryRoots})
	if err != nil {
		return fmt.Errorf("open knowledge state: %w", err)
	}
	defer svc.Close()
	server := newServer(svc, cfg.ReadOnly)
	if cfg.Listen == "" {
		return server.Run(ctx, &mcp.StdioTransport{})
	}
	handler, err := httpHandler(server, cfg, token, svc)
	if err != nil {
		return err
	}
	fmt.Fprintf(stderr, "superretometer %s (%s): serving MCP on %s/mcp\n", version, revision, cfg.Listen)
	return serveHTTP(ctx, handler, cfg.Listen)
}

func checkListenAddress(address string) error {
	_, port, err := net.SplitHostPort(address)
	if err != nil {
		return fmt.Errorf("invalid --listen address: %w", err)
	}
	if port == "" {
		return errors.New("--listen requires a port")
	}
	return nil
}

type toolCaller interface {
	Call(context.Context, string, map[string]any) (any, error)
}

func newServer(caller toolCaller, readOnly bool) *mcp.Server {
	server := mcp.NewServer(&mcp.Implementation{Name: "superretometer", Version: version}, &mcp.ServerOptions{
		Instructions: "Superretometer assesses evidence and provenance. Propose tools only queue changes. Execute a proposal explicitly to validate and apply it. Warrant and gate results assess supplied evidence; they do not independently certify it.",
	})
	for _, definition := range toolDefinitions() {
		if readOnly && !definition.ReadOnly {
			continue
		}
		name := definition.Name
		closed, destructive := false, definition.Destructive
		tool := &mcp.Tool{Name: name, Description: definition.Description, InputSchema: definition.Schema,
			Annotations: &mcp.ToolAnnotations{ReadOnlyHint: definition.ReadOnly, DestructiveHint: &destructive,
				IdempotentHint: definition.Idempotent, OpenWorldHint: &closed}}
		mcp.AddTool(server, tool, func(ctx context.Context, _ *mcp.CallToolRequest, args map[string]any) (*mcp.CallToolResult, any, error) {
			operation := name
			if name == "check_simulation_gates" || name == "check_implementation_gates" {
				operation = strings.Replace(name, "check_", "evaluate_", 1)
				args = map[string]any{"claim_ko_id": args["ko_id"]}
			}
			result, err := caller.Call(ctx, operation, args)
			if err != nil {
				return nil, nil, err
			}
			payload, err := json.Marshal(result)
			if err != nil {
				return nil, nil, err
			}
			return &mcp.CallToolResult{Content: []mcp.Content{&mcp.TextContent{Text: string(payload)}}}, nil, nil
		})
	}
	return server
}

func httpHandler(server *mcp.Server, cfg config, token string, caller toolCaller) (http.Handler, error) {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		if _, err := caller.Call(r.Context(), "orientation", nil); err != nil {
			http.Error(w, "knowledge state unavailable", http.StatusServiceUnavailable)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{"status": "ok", "version": version, "revision": revision, "read_only": cfg.ReadOnly})
	})
	var endpoint http.Handler = mcp.NewStreamableHTTPHandler(func(*http.Request) *mcp.Server { return server }, &mcp.StreamableHTTPOptions{
		SessionTimeout: 30 * time.Minute, DisableLocalhostProtection: cfg.BehindProxy, MaxRequestBodyBytes: 4 << 20,
	})
	protection := http.NewCrossOriginProtection()
	allowedOrigins := make(map[string]bool)
	for _, origin := range cfg.AllowedOrigins {
		if err := protection.AddTrustedOrigin(origin); err != nil {
			return nil, fmt.Errorf("invalid allowed origin: %w", err)
		}
		allowedOrigins[origin] = true
	}
	endpoint = protection.Handler(endpoint)
	if token != "" {
		next := endpoint
		endpoint = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), []byte("Bearer "+token)) != 1 {
				w.Header().Set("WWW-Authenticate", `Bearer realm="superretometer"`)
				http.Error(w, "authentication required", http.StatusUnauthorized)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
	// CSRF protection intentionally skips safe methods. MCP also requires Origin
	// validation for GET streams, so enforce the endpoint boundary for all methods.
	next := endpoint
	endpoint = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origins := r.Header.Values("Origin")
		if len(origins) > 0 {
			origin := r.Header.Get("Origin")
			parsed, err := url.Parse(origin)
			scheme := "http"
			if r.TLS != nil {
				scheme = "https"
			}
			sameOrigin := err == nil && parsed.User == nil && parsed.Path == "" && parsed.RawQuery == "" && parsed.Fragment == "" && parsed.Scheme == scheme && strings.EqualFold(parsed.Host, r.Host)
			if len(origins) != 1 || (!allowedOrigins[origin] && !sameOrigin) {
				http.Error(w, "untrusted origin", http.StatusForbidden)
				return
			}
		}
		next.ServeHTTP(w, r)
	})
	mux.Handle("/mcp", endpoint)
	return mux, nil
}

func serveHTTP(ctx context.Context, handler http.Handler, listen string) error {
	srv := &http.Server{Addr: listen, Handler: handler, ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 60 * time.Second}
	listener, err := net.Listen("tcp", listen)
	if err != nil {
		return err
	}
	finished := make(chan struct{})
	shutdownDone := make(chan struct{})
	defer close(finished)
	go func() {
		defer close(shutdownDone)
		select {
		case <-ctx.Done():
			shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			if err := srv.Shutdown(shutdown); err != nil {
				_ = srv.Close()
			}
		case <-finished:
		}
	}()
	if err := srv.Serve(listener); !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	if ctx.Err() != nil {
		<-shutdownDone
	}
	return nil
}

func checkHealth(ctx context.Context, listen string) error {
	if listen == "" {
		listen = "127.0.0.1:3010"
	}
	host, port, err := net.SplitHostPort(listen)
	if err != nil {
		return err
	}
	if host == "" || host == "0.0.0.0" || host == "::" {
		host = "127.0.0.1"
	}
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, "http://"+net.JoinHostPort(host, port)+"/healthz", nil)
	if err != nil {
		return err
	}
	response, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("healthcheck: HTTP %d", response.StatusCode)
	}
	return nil
}
