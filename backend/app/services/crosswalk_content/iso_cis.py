"""ISO/IEC 27001:2022 Annex A → CIS Critical Security Controls v8.

CIS publishes a mapping of the v8 safeguards to ISO/IEC 27001:2022. A safeguard is
narrow ("Require MFA for remote network access") and an Annex A control broad ("Secure
authentication"), so almost every row is ``intersects``: the safeguard is one way the
control is met and the control asks for more. ``equivalent`` only where one safeguard is
the whole control (classification scheme, clock synchronisation, supplier agreements,
separation of environments, web filtering, lessons learned).
"""

FROM = "iso-27001-2022"
TO = "cis-controls-v8"
SOURCE = "NexusLine curated; aligned with the CIS Controls v8 mapping to ISO/IEC 27001:2022"

ROWS = """
A.5.9    1.1   intersects  0.85  Inventory of enterprise assets
A.5.9    2.1   intersects  0.8   Inventory of software
A.5.9    3.2   intersects  0.7   Inventory of data
A.5.12   3.7   equivalent  0.85  A data classification scheme
A.5.13   3.7   related     0.6   Labelling follows the classification scheme
A.5.14   3.10  related     0.65  Sensitive data encrypted in transit
A.5.14   3.8   related     0.6   Data flows are documented
A.5.15   3.3   intersects  0.7   Data access control lists
A.5.15   6.1   intersects  0.7   Access granting process
A.5.15   6.2   intersects  0.7   Access revoking process
A.5.15   6.8   intersects  0.7   Role-based access control
A.5.15   6.7   related     0.65  Centralised access control
A.5.16   5.1   intersects  0.75  Inventory of accounts
A.5.16   5.5   related     0.65  Inventory of service accounts
A.5.16   5.6   related     0.65  Centralised account management
A.5.16   6.1   intersects  0.7   Identities created through a granting process
A.5.16   6.2   intersects  0.7   Identities removed through a revoking process
A.5.16   6.6   related     0.6   Inventory of authentication systems
A.5.17   5.2   intersects  0.75  Unique passwords
A.5.18   6.1   intersects  0.75  Access rights granted
A.5.18   6.2   intersects  0.75  Access rights revoked
A.5.18   5.3   intersects  0.7   Dormant accounts disabled
A.5.19   15.2  intersects  0.8   Service provider management policy
A.5.19   15.1  intersects  0.7   Inventory of service providers
A.5.19   15.3  related     0.65  Service providers classified
A.5.20   15.4  equivalent  0.85  Security requirements in service provider contracts
A.5.21   15.4  related     0.6   ICT supply chain requirements in contracts
A.5.21   16.5  related     0.6   Trusted third-party software components
A.5.22   15.6  intersects  0.8   Service providers monitored
A.5.22   15.5  intersects  0.75  Service providers assessed
A.5.22   15.7  related     0.65  Service providers decommissioned securely
A.5.24   17.4  intersects  0.8   Incident response process
A.5.24   17.1  intersects  0.75  Personnel designated for incident handling
A.5.24   17.5  intersects  0.7   Key roles and responsibilities
A.5.24   17.2  related     0.65  Contact information for incident reporting
A.5.24   17.6  related     0.65  Communication mechanisms during response
A.5.24   17.9  related     0.65  Incident thresholds
A.5.25   17.9  intersects  0.7   Thresholds separate events from incidents
A.5.26   17.4  intersects  0.75  Responding per the incident response process
A.5.27   17.8  equivalent  0.8   Post-incident reviews
A.5.29   11.1  related     0.6   Data recovery during disruption
A.5.30   11.1  related     0.6   Data recovery process
A.5.33   3.4   related     0.6   Data retention
A.5.34   3.1   related     0.6   Data management process
A.6.3    14.1  intersects  0.85  Security awareness programme
A.6.3    14.2  intersects  0.7   Social engineering training
A.6.3    14.3  intersects  0.7   Authentication best practice training
A.6.3    14.4  intersects  0.7   Data handling training
A.6.3    14.5  intersects  0.65  Unintentional data exposure training
A.6.3    14.6  intersects  0.7   Incident recognition and reporting training
A.6.3    14.9  intersects  0.75  Role-specific training
A.6.7    12.7  related     0.65  Remote devices use VPN and enterprise AAA
A.6.7    13.5  related     0.65  Access control for remote assets
A.6.8    14.6  intersects  0.75  Workforce trained to report incidents
A.6.8    17.3  intersects  0.75  Enterprise incident reporting process
A.7.7    4.3   related     0.6   Automatic session locking
A.7.10   3.9   intersects  0.7   Encrypting removable media
A.7.10   10.3  related     0.6   Autorun disabled for removable media
A.7.10   10.4  related     0.6   Removable media scanned
A.7.14   3.5   related     0.65  Secure disposal of data
A.8.1    3.6   related     0.65  Encrypting data on end-user devices
A.8.1    4.3   related     0.6   Session locking on devices
A.8.1    4.5   related     0.6   Firewall on end-user devices
A.8.1    4.10  related     0.6   Device lockout on portable devices
A.8.1    4.11  related     0.65  Remote wipe on portable devices
A.8.1    4.12  related     0.6   Separate enterprise workspaces on mobile devices
A.8.2    5.4   intersects  0.75  Administrator privileges in dedicated accounts
A.8.2    6.5   related     0.65  MFA for administrative access
A.8.2    12.8  related     0.6   Dedicated computing resources for administration
A.8.3    3.3   intersects  0.75  Data access control lists
A.8.3    6.8   related     0.65  Role-based access control
A.8.5    6.3   intersects  0.75  MFA for externally exposed applications
A.8.5    6.4   intersects  0.75  MFA for remote network access
A.8.5    6.5   intersects  0.75  MFA for administrative access
A.8.5    6.7   related     0.6   Centralised access control
A.8.5    12.5  related     0.6   Centralised network AAA
A.8.7    10.1  intersects  0.85  Anti-malware software
A.8.7    10.2  intersects  0.7   Automatic signature updates
A.8.7    10.6  intersects  0.7   Central management of anti-malware
A.8.7    10.7  related     0.65  Behaviour-based anti-malware
A.8.7    10.5  related     0.6   Anti-exploitation features
A.8.7    9.7   related     0.65  Email server anti-malware
A.8.8    7.1   intersects  0.85  Vulnerability management process
A.8.8    7.2   intersects  0.8   Remediation process
A.8.8    7.3   intersects  0.7   Operating system patching
A.8.8    7.4   intersects  0.7   Application patching
A.8.8    7.5   intersects  0.75  Internal vulnerability scans
A.8.8    7.6   intersects  0.75  External vulnerability scans
A.8.8    7.7   intersects  0.75  Remediating detected vulnerabilities
A.8.8    16.2  related     0.6   Handling reported software vulnerabilities
A.8.8    18.2  related     0.6   External penetration tests find vulnerabilities
A.8.8    18.3  related     0.6   Remediating penetration test findings
A.8.8    18.5  related     0.6   Internal penetration tests find vulnerabilities
A.8.9    4.1   intersects  0.85  Secure configuration process
A.8.9    4.2   intersects  0.8   Secure configuration of network infrastructure
A.8.9    4.6   related     0.6   Securely managing assets and software
A.8.9    4.7   related     0.65  Default accounts managed
A.8.9    4.8   related     0.65  Unnecessary services disabled
A.8.9    16.7  related     0.65  Hardening templates for application infrastructure
A.8.10   3.5   intersects  0.75  Secure disposal of data
A.8.10   3.4   related     0.65  Data retention limits
A.8.12   3.13  intersects  0.8   Data loss prevention
A.8.12   3.14  related     0.6   Logging access to sensitive data
A.8.13   11.1  intersects  0.75  Data recovery process
A.8.13   11.2  intersects  0.8   Automated backups
A.8.13   11.3  intersects  0.7   Protecting recovery data
A.8.13   11.4  intersects  0.7   Isolated recovery data
A.8.13   11.5  intersects  0.7   Testing data recovery
A.8.15   8.1   intersects  0.75  Audit log management process
A.8.15   8.2   intersects  0.8   Collecting audit logs
A.8.15   8.3   related     0.65  Log storage
A.8.15   8.5   intersects  0.7   Detailed audit logs
A.8.15   8.9   intersects  0.7   Centralised audit logs
A.8.15   8.10  intersects  0.7   Log retention
A.8.15   8.6   related     0.6   DNS query logs
A.8.15   8.7   related     0.6   URL request logs
A.8.15   8.8   related     0.6   Command-line logs
A.8.15   8.12  related     0.6   Service provider logs
A.8.16   8.11  intersects  0.75  Audit log reviews
A.8.16   13.1  intersects  0.75  Centralised security event alerting
A.8.16   13.2  related     0.65  Host-based intrusion detection
A.8.16   13.3  related     0.65  Network intrusion detection
A.8.16   13.6  related     0.65  Network traffic flow logs
A.8.16   13.11 related     0.6   Alerting thresholds tuned
A.8.17   8.4   equivalent  0.9   Standardised time synchronisation
A.8.18   5.4   related     0.6   Administrative tooling restricted to admin accounts
A.8.19   2.3   intersects  0.7   Unauthorised software addressed
A.8.19   2.5   intersects  0.7   Software allowlisting
A.8.19   2.6   related     0.6   Library allowlisting
A.8.19   2.7   related     0.6   Script allowlisting
A.8.20   12.1  intersects  0.65  Network infrastructure kept up to date
A.8.20   12.2  intersects  0.75  Secure network architecture
A.8.20   12.3  intersects  0.75  Network infrastructure managed securely
A.8.20   12.6  related     0.65  Secure management protocols
A.8.20   4.2   related     0.6   Network device configuration
A.8.20   13.10 related     0.6   Application layer filtering
A.8.22   13.4  intersects  0.75  Traffic filtering between segments
A.8.22   3.12  intersects  0.7   Segmenting by data sensitivity
A.8.22   12.2  related     0.65  Segmented architecture
A.8.22   12.8  related     0.6   Dedicated administration resources
A.8.23   9.3   equivalent  0.8   Network-based URL filters
A.8.23   9.2   related     0.65  DNS filtering
A.8.24   3.10  intersects  0.7   Encrypting data in transit
A.8.24   3.11  intersects  0.7   Encrypting data at rest
A.8.24   3.6   related     0.65  Encrypting end-user devices
A.8.24   3.9   related     0.6   Encrypting removable media
A.8.25   16.1  intersects  0.85  Secure application development process
A.8.26   16.1  related     0.6   Security requirements within development
A.8.26   16.10 related     0.6   Secure design principles
A.8.27   16.10 intersects  0.75  Secure design principles in architectures
A.8.27   12.2  related     0.6   Secure network architecture
A.8.28   16.12 intersects  0.7   Code-level security checks
A.8.28   16.11 related     0.65  Vetted security components
A.8.28   16.5  related     0.6   Trusted third-party components
A.8.28   16.9  related     0.6   Developer training in secure coding
A.8.29   16.13 intersects  0.7   Application penetration testing
A.8.29   16.12 related     0.6   Code-level checks
A.8.31   16.8  equivalent  0.85  Production and non-production separated
"""
