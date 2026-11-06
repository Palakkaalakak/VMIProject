@echo off
rem Start IBKR's Client Portal Gateway with the conf.tws.yaml profile (the one that serves fundamentals).
rem IBKR's bin\run.bat ignores its config argument, so this starts Java directly. Works from cmd and PowerShell.
rem Usage:  tools\start_cp_gateway.cmd C:\path\to\clientportal.gw     (default: current folder)
setlocal
if not "%~1"=="" cd /d "%~1"
if not exist "root\conf.tws.yaml" (
  echo root\conf.tws.yaml not found in "%CD%". Pass the clientportal.gw folder: tools\start_cp_gateway.cmd C:\path\to\clientportal.gw
  exit /b 1
)
java -server "-Dvertx.disableDnsResolver=true" "-Djava.net.preferIPv4Stack=true" -classpath "root\;dist\ibgroup.web.core.iblink.router.clientportal.gw.jar;build\lib\runtime\*" ibgroup.web.core.clientportal.gw.GatewayStart --conf conf.tws.yaml
