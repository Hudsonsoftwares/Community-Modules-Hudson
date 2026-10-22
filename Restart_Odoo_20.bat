@echo off
echo Restarting Odoo 20 Service...
net stop odoo-server-20.0
net start odoo-server-20.0
echo.
echo Odoo 20 Service restarted successfully!
pause
