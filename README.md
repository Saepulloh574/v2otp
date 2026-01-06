[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

//restart.
shutdown /r /t 0

//cek
reg query "HKLM\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full" /v Release

//install
choco install git -y

/install 
choco install python -y

//close terminal
//open terminal

//clone 
git clone https://github.com/Saepulloh574/v2otp
