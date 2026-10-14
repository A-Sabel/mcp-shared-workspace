const path = require("node:path");

const repositoryRoot = path.resolve(__dirname, "../..");

module.exports = {
  apps: [
    {
      name: "mcp-workspace",
      script: path.join(repositoryRoot, ".venv", "Scripts", "python.exe"),
      interpreter: "none",
      args: "-m server.http_runner",
      cwd: repositoryRoot,
      exec_mode: "fork",
      instances: 1,
      autorestart: true,
      stop_exit_codes: [3221225786],
      watch: false,
      windowsHide: true,
      time: true,
    },
  ],
};
