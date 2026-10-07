module.exports = {
  apps: [
    {
      name: "mcp-workspace",
      script: ".\\.venv\\Scripts\\python.exe",
      interpreter: "none",
      args: "-m server.http_runner",
      cwd: ".",
      autorestart: true,
      stop_exit_codes: [3221225786],
      watch: false,
      windowsHide: true,
      time: true,
    },
  ],
};
