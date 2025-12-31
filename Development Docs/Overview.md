# Overview
---
## The basic process
The following is the basic process that should be followed for all game servers:

### Create an LXC Container
First things first an LXC Container should be created, this should be pretty a pretty basic preconfigured environment, but could have modifications to make it more ideal for specific games: Minecraft - Java preinstalled, Steam - Steamcmd preinstalled, etc.
12/30/25: I am giving up on customizing the actual LXC, theres too many things that could go wrong for a 30 second time save.

### Run setup script
Next pre-configured scripts should be ran to install the correct game and the correct version. These scripts should provide as much configuration as possible, but should not be so specific that purpose specific customizations should be made at this point.

### Apply customizations
Customizations should be optionally be made before creation, but it is important that they be applied properly and are easily updatable at any time.

### Running and the console
The game should now basically run on its own, but it is important that the console is easily accessible to do any normal server functions (Whether it be through rcon or just controlling the process or whatever its called). It is also important that files be easily accessible and modifiable. (Maybe a text editor built in?) Additionally, it would be very helpful to have a sftp service for accessing files in bulk.

## Game Codes
"Game Codes" are a string created to identify specific games that servers are ran for. These should be short and sweet, identifiable but distinctive. It is important to not have game codes that look like they belong to other games, or look like they could fit two different games, as this could invite a shit ton of confusion and problems for future developers (Me😐)