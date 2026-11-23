package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"time"

	"github.com/euthm/superretometer/go/internal/graph"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

func main() {
	snapshot := flag.String("snapshot", "", "Path to a JSON knowledge graph snapshot")
	listen := flag.String("listen", "", "Loopback HTTP address such as 127.0.0.1:3010; omit for stdio")
	flag.Parse()
	if err := run(context.Background(), *snapshot, *listen); err != nil {
		log.Fatal(err)
	}
}

func run(ctx context.Context, snapshot, listen string) error {
	if snapshot == "" {
		return fmt.Errorf("-snapshot is required")
	}
	file, err := os.Open(snapshot)
	if err != nil {
		return err
	}
	g, err := graph.Load(file)
	file.Close()
	if err != nil {
		return err
	}
	server := newServer(g)
	if listen == "" {
		return server.Run(ctx, &mcp.StdioTransport{})
	}
	if err := checkListenAddress(listen); err != nil {
		return err
	}
	return serveHTTP(server, listen)
}

func checkListenAddress(address string) error {
	_, _, err := net.SplitHostPort(address)
	return err
}

type orientationArgs struct {
	Scope string `json:"scope,omitempty" jsonschema:"Optional scope filter"`
}

type objectArgs struct {
	ID string `json:"ko_id" jsonschema:"Knowledge object ID"`
}

type warrantArgs struct {
	ID string `json:"conclusion_ko_id" jsonschema:"Conclusion knowledge object ID"`
}

func newServer(g *graph.Graph) *mcp.Server {
	server := mcp.NewServer(&mcp.Implementation{
		Name: "superretometer", Version: "0.9.0",
	}, nil)

	addTool(server, "orientation", "Return current state of the knowledge graph", func(args orientationArgs) any {
		return g.Orientation(args.Scope, time.Now())
	})
	addTool(server, "check_warrant", "Assess whether a conclusion is warranted", func(args warrantArgs) any {
		return g.CheckWarrant(args.ID)
	})
	addTool(server, "justification_path", "Get the justification path for a Knowledge Object", func(args objectArgs) any {
		return g.JustificationPath(args.ID)
	})
	addTool(server, "impact_set", "Find KOs affected by a change", func(args objectArgs) any {
		return g.ImpactSet(args.ID)
	})
	return server
}

func addTool[Args any](server *mcp.Server, name, description string, call func(Args) any) {
	mcp.AddTool(server, &mcp.Tool{Name: name, Description: description},
		func(_ context.Context, _ *mcp.CallToolRequest, args Args) (*mcp.CallToolResult, any, error) {
			result, err := json.Marshal(call(args))
			if err != nil {
				return nil, nil, err
			}
			return &mcp.CallToolResult{Content: []mcp.Content{&mcp.TextContent{Text: string(result)}}}, nil, nil
		})
}

func httpHandler(server *mcp.Server) http.Handler {
	mux := http.NewServeMux()
	mux.Handle("/mcp", mcp.NewStreamableHTTPHandler(func(*http.Request) *mcp.Server {
		return server
	}, nil))
	return mux
}

func serveHTTP(server *mcp.Server, listen string) error {
	srv := &http.Server{
		Addr:              listen,
		Handler:           httpHandler(server),
		ReadHeaderTimeout: 5 * time.Second,
		IdleTimeout:       60 * time.Second,
	}
	return srv.ListenAndServe()
}
