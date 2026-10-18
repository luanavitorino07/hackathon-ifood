import http from "node:http";
import httpProxy from "http-proxy";
const proxy = httpProxy.createProxyServer({ ws: true });
proxy.on("error", (_e, _req, res) => {
  if (res.writeHead) {
    res.writeHead(502, { "Content-Type": "text/plain" });
    res.end("Inicie a API (8000) e o Expo Web (8081).");
  }
});
const server = http.createServer((req, res) =>
  proxy.web(req, res, {
    target: req.url.startsWith("/api/")
      ? "http://127.0.0.1:8000"
      : "http://127.0.0.1:8081",
  }),
);
server.on("upgrade", (req, socket, head) =>
  proxy.ws(req, socket, head, { target: "http://127.0.0.1:8081" }),
);
server.listen(8080, "127.0.0.1", () =>
  console.log("PedIA: http://localhost:8080"),
);
