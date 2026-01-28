# Networking Overview

## Explaination
In order for containers to communicate with both each other and everything else, we need to ensure that they are all networked together. However, to avoid any issues caused by external services/devices on the network, I believe it is important that PGSM be on its own isolated network. However, the fact that each container may be on a different physical device makes the networking need to be either super advanced, or handled external from PGSM (a seperate router that handles VLANs).

## Overview
PGSM will have all of it's containers be attached to a PGSM specific VLAN.
However, since these containers need to be able to communicate to the outside world, the PGSM "Master" container must also be connected to whatever network everything else is on.
The PGSM server containers will only communicate through the Master container, which will be running Nginx Proxy Manager, proxying all important networking through safely.