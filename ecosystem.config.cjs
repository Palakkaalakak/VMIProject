module.exports = {
  apps: [{
    name: 'vmi',
    script: 'python3',
    args: '-m vmi.api',
    cwd: '/home/user/webapp',
    env: { PYTHONPATH: '/home/user/webapp', VMI_PORT: '8000', VMI_HOST: '0.0.0.0' },
    watch: false, instances: 1, exec_mode: 'fork', autorestart: true
  }]
}
