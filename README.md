# Boiler Control Lite
Boiler Control Lite

install :

cd ~/domoticz/plugins 

mkdir BoilerCLite

sudo apt-get update

sudo apt-get install git

git clone https://github.com/Erwanweb/BoilerCLite.git BoilerCLite

cd BoilerCLite

sudo chmod +x plugin.py

sudo /etc/init.d/domoticz.sh restart

Upgrade :

cd ~/domoticz/plugins/BoilerCLite

git reset --hard

git pull --force

sudo chmod +x plugin.py

sudo /etc/init.d/domoticz.sh restart
