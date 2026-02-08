module.exports = {
  apps: [{
    name: 'kiro-gateway',
    script: 'main.py',
    interpreter: 'python3',
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: '1G',
    env: {
      AUTH_MODE: 'per_request',
      SERVER_HOST: '0.0.0.0',
      SERVER_PORT: '8000',
      LOG_LEVEL: 'INFO'
    },
    error_file: './logs/err.log',
    out_file: './logs/out.log',
    log_file: './logs/combined.log',
    time: true
  }]
};
