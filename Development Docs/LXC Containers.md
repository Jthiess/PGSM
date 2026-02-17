# LXC Container Information
LXC Containers are cool, but they are certainly not as powerful for many servers as Docker is. However, in this particular situation, Docker is not an option due to the load needing to be spread across multiple physical systems. Following is all of the options that proxmox provides when creating a new LXC Container.

| Attribute              | Source                               |
| ---------------------- | ------------------------------------ |
| Password               | Randomly Generated                   |
| Hostname               | PGSM-[Game Code]-[Partial UUID]      |
| Unprivileged Container | True (Static)                        |
| CT ID                  | 500+[Lowest available number]        |
| Node                   | Specified, at least at first.        |
| SSH public key(s)      | User will upload public key (Global) |
| Disk size (GiB)        | User Specified                       |
| Cores                  | User Specified                       |
| Memory                 | User Specified                       |
| Bridge                 | PGSM                                 |
| IPv4                   | Lowest available IP                  |
| DNS Domain             | PGSM.lan                             |
| DNS Servers            | 1.1.1.1                              |
