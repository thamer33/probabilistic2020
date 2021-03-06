.. _install-ref:

Installation
------------

.. image:: https://travis-ci.org/KarchinLab/probabilistic2020.svg?branch=master
    :target: https://travis-ci.org/KarchinLab/probabilistic2020

Python Package Installation
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Using the python package installation, all the required python packages for the probabibilistic 20/20 test will automatically be installed for you. We recommend use of python version 3.6, if possible. 

To install the package into python you can use `pip`. If you are installing to a system wide python then you may need to use `sudo` before the pip command.

.. code-block:: bash

    $ pip install probabilistic2020

The scripts for Probabilstic 20/20 can then be found in `Your_Python_Root_Dir/bin`. You can
check the installation with the following:

.. code-block:: bash

    $ which probabilistic2020
    $ probabilistic2020 --help

Local installation
~~~~~~~~~~~~~~~~~~

Local installation is a good option if you do not have privilege to install a python package and already have the required packages.  The source files can also be manually downloaded from github at https://github.com/KarchinLab/probabilistic2020/releases.

**Required packages:**

* numpy
* scipy
* pandas>=0.17.0
* pysam

If you don't have the above required packages, you will need to install them. For the following commands to work you will need `pip <http://pip.readthedocs.org/en/latest/installing.html>`_. If you are using a system wide python, you will need to use `sudo` before the pip command.

.. code-block:: bash

    $ cd probabilstic2020
    $ pip install -r requirements.txt

Next you will need to build the Probabilistic 20/20 source files. This is can be accomplished in one command.

.. code-block:: bash

    $ make build

Once finished building you can then use the scripts in the `probabilstic2020/prob2020/console` directory. You can check the build worked by the following:

.. code-block:: bash

    $ python prob2020/cosole/probabilistic2020.py --help
