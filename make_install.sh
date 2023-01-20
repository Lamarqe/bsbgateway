find -type f -name \*.py -exec install -D {} /usr/local/bsbgateway/{} \;
chmod +x /usr/local/bsbgateway/bsbgateway.py
cp bsbgateway.service /etc/systemd/system/bsbgateway.service
systemctl enable bsbgateway
systemctl start bsbgateway

