"""PCI DSS v4.0.1 → CIS Critical Security Controls v8.

CIS publishes a mapping of the v8 safeguards to PCI DSS v4.0. Rows follow the content of
both templates. A PCI requirement scoped to the CDE and a CIS safeguard scoped to the
enterprise rarely say exactly the same thing, so rows are ``intersects`` or ``related``;
``equivalent`` for vendor default accounts, time synchronisation and the service
provider inventory.
"""

FROM = "pci-dss-4.0"
TO = "cis-controls-v8"
SOURCE = "NexusLine curated; aligned with the CIS Controls v8 mapping to PCI DSS v4.0"

ROWS = """
1.2      4.2    intersects  0.7   Network devices configured securely
1.2      4.4    intersects  0.65  Firewalls on servers
1.2      12.2   related     0.6   Secure network architecture
1.2.1    4.2    related     0.6   Network configuration standards
1.2.5    4.8    related     0.6   Unnecessary services and ports disabled
1.3      13.4   intersects  0.7   Traffic filtering between segments
1.3      3.12   related     0.6   Segmenting sensitive data processing
1.3      12.2   related     0.6   Segmented architecture
1.4      12.2   related     0.6   Trusted and untrusted networks in the architecture
1.4      13.10  related     0.6   Application layer filtering
1.4.1    13.4   related     0.6   Filtering between networks
1.5      4.5    intersects  0.7   Firewall on end-user devices
2.2      4.1    intersects  0.8   Secure configuration process
2.2.1    4.1    intersects  0.75  Configuration standards
2.2.2    4.7    equivalent  0.85  Default accounts managed
2.2.7    12.6   intersects  0.7   Encrypted administrative protocols
3.1      3.1    related     0.6   Data management process
3.2.1    3.4    intersects  0.75  Data retention
3.5.1    3.11   intersects  0.7   Encrypting sensitive data at rest
4.2      3.10   intersects  0.8   Encrypting sensitive data in transit
4.2.1    3.10   intersects  0.75  Strong protocols in transit
5.2      10.1   intersects  0.8   Anti-malware deployed
5.2.1    10.1   intersects  0.8   Anti-malware software
5.3      10.2   intersects  0.7   Signatures kept current
5.3      10.6   related     0.65  Anti-malware centrally managed
5.3.1    10.2   intersects  0.75  Automatic updates
5.4      9.5    related     0.6   DMARC against spoofed email
5.4      9.7    related     0.6   Email anti-malware
5.4      14.2   related     0.6   Social engineering awareness
6.1      16.1   related     0.65  Development process defined
6.2      16.1   intersects  0.75  Secure development process
6.2      16.9   related     0.6   Developer training
6.2      16.12  related     0.65  Code-level security checks
6.2.1    16.1   intersects  0.7   Secure development practices
6.3      7.1    intersects  0.75  Vulnerability management process
6.3      16.4   related     0.6   Inventory of third-party software components
6.3      16.6   related     0.65  Severity rating of vulnerabilities
6.3.1    7.1    intersects  0.75  Vulnerabilities identified and ranked
6.3.3    7.3    intersects  0.75  Operating system patching
6.3.3    7.4    intersects  0.75  Application patching
6.3.3    7.7    related     0.65  Remediation
6.4      13.10  intersects  0.65  Application layer filtering for web applications
6.5      16.8   related     0.65  Production separated from non-production
7.2      6.1    intersects  0.7   Access granting
7.2      6.8    intersects  0.7   Role-based access
7.2.1    6.8    intersects  0.75  Access control model by role
7.3      6.7    intersects  0.7   Centralised access control
8.2      5.1    intersects  0.7   Inventory of accounts
8.2      5.3    intersects  0.65  Inactive accounts disabled
8.2      6.2    related     0.65  Access revoked
8.3      5.2    intersects  0.7   Passwords managed
8.4      6.4    intersects  0.7   MFA for remote access
8.4      6.5    intersects  0.7   MFA for administrative access
8.4.2    6.3    related     0.6   MFA for exposed applications
8.4.2    6.4    related     0.65  MFA for remote access
8.4.2    6.5    related     0.65  MFA for administrative access
8.6      5.5    intersects  0.7   Service accounts managed
9.4      3.9    related     0.6   Removable media protected
10.2     8.2    intersects  0.8   Audit logs collected
10.2     8.5    intersects  0.75  Detailed audit logs
10.2.1   8.2    intersects  0.8   Logging enabled
10.3     8.9    related     0.65  Logs centralised and protected
10.4     8.11   intersects  0.8   Log reviews
10.4.1   8.11   intersects  0.75  Frequent log reviews
10.5     8.10   intersects  0.8   Log retention
10.6     8.4    equivalent  0.9   Time synchronisation
10.7     13.1   related     0.6   Alerting on control failures
11.3     7.5    intersects  0.75  Internal vulnerability scans
11.3     7.6    intersects  0.75  External vulnerability scans
11.3.1   7.5    intersects  0.8   Internal scans
11.4     18.1   intersects  0.8   Penetration testing programme
11.4     18.2   intersects  0.75  External penetration tests
11.4     18.3   intersects  0.7   Findings remediated
11.4     18.5   intersects  0.75  Internal penetration tests
11.4.1   18.1   related     0.65  Penetration test methodology
11.5     13.2   related     0.6   Host intrusion detection
11.5     13.3   intersects  0.7   Network intrusion detection
11.5     13.8   intersects  0.65  Network intrusion prevention
12.5     1.1    related     0.6   Inventory of in-scope assets
12.5     3.8    related     0.65  Data flows documented
12.5     12.4   related     0.6   Architecture diagrams
12.6     14.1   intersects  0.85  Security awareness programme
12.8     15.2   intersects  0.75  Service provider management policy
12.8.1   15.1   equivalent  0.85  Inventory of service providers
12.9     15.4   related     0.6   Service provider responsibilities
12.10    17.4   intersects  0.8   Incident response process
12.10    17.7   related     0.6   Incident response exercises
12.10.1  17.4   intersects  0.8   Incident response plan
"""
