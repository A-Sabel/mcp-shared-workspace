module.exports = {
  apps: [
    {
      name: "mcp-workspace",
      script: ".\\.venv\\Scripts\\python.exe",
      interpreter: "none",
      args: "-m server.http_runner",
      cwd: ".",
      autorestart: true,
      watch: false,
      time: true,
    },
  ],
};
