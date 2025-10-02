Speedometer
===========

*Speedometer is looking for a maintainer*. Please open a ticket on github if you believe you could help maintain this project.

Measure and display the rate of data across a network connection or data being stored in a file.

* [Speedometer Home Page](https://excess.org/speedometer/)


New Changes
------------

1. Python 3 is required now, mac os x platform is included.

2. Use python `psutil` module, instead of /dev/net for maximal compatibility.

3. New -d options, support to measure data from running external shell standard output.

   * python speedometer.py -d "ls -lR /"

   * python speedometer.py -d "curl https://download.site/file.iso --output -"

   * python speedometer.py -d "curl https://download.site/file.iso --output - | tee newfile.iso"

4. Support data source from `standard input` or `pipe line`, working only for plain text mode.

   * cat /dev/urandom | python speedometer.py

   * python speedometer.py < /dev/urandom

   * curl --output - https://download.site/file.iso 2>/dev/null | python speedometer.py


Screen Shots
------------

![speedometer screen shot w/ transparent bg](https://excess.org/media/speedometer-transp1.png)
   
![speedometer screen shot w/ multiple graphs](https://excess.org/media/speedometer-light16.png)
