Speedometer
===========

Fork from <https://github.com/wardi/speedometer>

Measure and display the rate of data across a network connection or data being stored in a file.

* `Speedometer Home Page <http://excess.org/speedometer/>`_


New Changes
------------

1. Python 2.7, 3 is supported now, mac os x platform is included.

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

.. image:: http://excess.org/media/speedometer-transp1.png
   :alt: speedometer screen shot w/ transparent bg

.. image:: http://excess.org/media/speedometer-light16.png
   :alt: speedometer screen shot w/ multiple graphs
