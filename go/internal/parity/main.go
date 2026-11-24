// Command parity replays reference fixtures against Go without a Python runtime
// dependency in the production server. It is used only by check_go_parity.py.
package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"reflect"

	"github.com/euthm/superretometer/go/internal/graph"
	"github.com/euthm/superretometer/go/internal/service"
)

type request struct {
	Operation string          `json:"operation"`
	Snapshot  json.RawMessage `json:"snapshot"`
	Argument  string          `json:"argument"`
	Roots     []string        `json:"freshness_roots"`
	Tool      string          `json:"tool"`
	Arguments map[string]any  `json:"arguments"`
}

type response struct {
	Result any    `json:"result,omitempty"`
	Error  string `json:"error,omitempty"`
}

func execute(r request) (out response) {
	defer func() {
		if p := recover(); p != nil {
			out = response{Error: fmt.Sprintf("panic: %v", p)}
		}
	}()
	if r.Operation == "service_call" {
		file, err := os.CreateTemp("", "superretometer-parity-state-*.json")
		if err != nil {
			return response{Error: err.Error()}
		}
		defer os.Remove(file.Name())
		if _, err = file.Write(r.Snapshot); err != nil {
			_ = file.Close()
			return response{Error: err.Error()}
		}
		if err = file.Close(); err != nil {
			return response{Error: err.Error()}
		}
		s, err := service.Open(service.Options{SnapshotPath: file.Name(), FreshnessRoots: r.Roots})
		if err != nil {
			return response{Error: err.Error()}
		}
		defer s.Close()
		result, err := s.Call(context.Background(), r.Tool, r.Arguments)
		if err != nil {
			return response{Error: err.Error()}
		}
		state, err := s.Snapshot()
		if err != nil {
			return response{Error: err.Error()}
		}
		return response{Result: map[string]any{"result": result, "state": json.RawMessage(state)}}
	}
	g, err := graph.Load(bytes.NewReader(r.Snapshot))
	if err != nil {
		return response{Error: err.Error()}
	}
	if len(r.Roots) != 0 {
		method := reflect.ValueOf(g).MethodByName("WithFreshnessRoots")
		if !method.IsValid() {
			return response{Error: "Go graph does not expose WithFreshnessRoots"}
		}
		values := method.Call([]reflect.Value{reflect.ValueOf(r.Roots)})
		if len(values) == 1 {
			g = values[0].Interface().(*graph.Graph)
		}
	}
	methods := map[string]string{
		"check_warrant":        "CheckWarrant",
		"scan_anti_patterns":   "ScanAntiPatterns",
		"simulation_gates":     "SimulationGates",
		"implementation_gates": "ImplementationGates",
		"justification_path":   "JustificationPath",
		"impact_set":           "ImpactSet",
	}
	name, ok := methods[r.Operation]
	if !ok {
		return response{Error: "unsupported parity operation: " + r.Operation}
	}
	method := reflect.ValueOf(g).MethodByName(name)
	if !method.IsValid() {
		return response{Error: "Go graph does not expose " + name}
	}
	var args []reflect.Value
	if r.Operation != "scan_anti_patterns" {
		args = []reflect.Value{reflect.ValueOf(r.Argument)}
	}
	values := method.Call(args)
	if len(values) != 1 {
		return response{Error: "unexpected result arity for " + name}
	}
	return response{Result: values[0].Interface()}
}

func main() {
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 64*1024), 64*1024*1024)
	encoder := json.NewEncoder(os.Stdout)
	for scanner.Scan() {
		var r request
		if err := json.Unmarshal(scanner.Bytes(), &r); err != nil {
			_ = encoder.Encode(response{Error: err.Error()})
			continue
		}
		if err := encoder.Encode(execute(r)); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	}
	if err := scanner.Err(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
