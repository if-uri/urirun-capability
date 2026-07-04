// A capability node written in Go (a compiled, entirely different runtime),
// serving the SAME language-neutral capability contract as the JS node.
// Proves the URI-process "server" is language-independent: same wire protocol,
// same typed contract, different implementation.
package main

import (
	"encoding/json"
	"net/http"
	"os"
	"runtime"
)

type cap struct {
	URI     string      `json:"uri"`
	Effect  string      `json:"effect"`
	Input   interface{} `json:"input"`
	Output  interface{} `json:"output"`
	Backend string      `json:"backend"`
}

func caps() []cap {
	return []cap{{
		URI:    "sys://host/os/query/info",
		Effect: "query",
		Input:  map[string]interface{}{"type": "object", "properties": map[string]interface{}{}},
		Output: map[string]interface{}{
			"type":     "object",
			"required": []string{"ok", "os", "arch", "lang"},
		},
		Backend: "go:" + runtime.Version(),
	}}
}

func writeJSON(w http.ResponseWriter, code int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8862"
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]interface{}{"ok": true, "lang": "go", "capabilities": 1})
	})
	mux.HandleFunc("/capabilities", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]interface{}{"lang": "go", "capabilities": caps()})
	})
	mux.HandleFunc("/dispatch", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			URI     string                 `json:"uri"`
			Payload map[string]interface{} `json:"payload"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSON(w, 400, map[string]interface{}{"ok": false,
				"error": map[string]string{"category": "INVALID_ARGUMENT", "message": "bad json"}})
			return
		}
		if req.URI != "sys://host/os/query/info" {
			writeJSON(w, 404, map[string]interface{}{"ok": false,
				"error": map[string]string{"category": "NOT_FOUND", "message": "no such capability"}})
			return
		}
		host, _ := os.Hostname()
		writeJSON(w, 200, map[string]interface{}{"ok": true, "result": map[string]interface{}{
			"ok": true, "os": runtime.GOOS, "arch": runtime.GOARCH,
			"hostname": host, "lang": "go",
		}})
	})
	println("capability node (go) on :" + port)
	http.ListenAndServe("0.0.0.0:"+port, mux)
}
