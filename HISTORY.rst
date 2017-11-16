.. :changelog:

Release History
===============
0.2.4
+++++++++++++++
* Build device connection string internally vs iot command module
* Clean-up

0.2.3
+++++++++++++++
* Significant restructing of CLI, prioritizes pure Python solutions where possible
* Provides IoT Edge capabilities
* Adds following new commands:
* iot query 
* iot device show 
* iot device list 
* iot device create 
* iot device update 
* iot device delete 
* iot device twin show 
* iot device twin update 
* iot device module show 
* iot device module list 
* iot device module create 
* iot device module update 
* iot device module delete 
* iot device module twin show 
* iot device module twin update 
* iot device module twin replace 
* iot configuration apply 
* iot configuration create 
* iot configuration update 
* iot configuration delete 
* iot configuration show 
* iot configuration list
* Bug fixes

0.1.2
+++++++++++++++
* Updated extension metadata with tweaked Az CLI names.
* Device simulate supports receive count of infinity and message count of 0.

0.1.1
+++++++++++++++
* Collection of new commands most of which use IoT SDK as the provider
* Show and update device twin
* Invoke device method
* Device simulation
* Hub message send (Cloud-to-device) 
* New device message send (Device-to-cloud) supports http, amqp, mqtt
* Get SAS token