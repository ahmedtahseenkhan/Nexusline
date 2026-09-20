"""ISO/IEC 27001:2022 → PCI DSS v4.0.1.

PCI DSS applies to the cardholder data environment (CDE) and is prescriptive; an Annex A
control is organisation-wide and outcome-based. Most rows are therefore ``intersects``:
the ISO control's scope is wider, the PCI requirement's detail is finer, and neither
fully meets the other. ``superset`` is used once, where the ISO control is plainly the
whole of the PCI requirement and more (A.5.10 acceptable use covers the end-user
technology policies of 12.2). ``related`` marks the "processes defined" requirements
(x.1) against documented operating procedures.
"""

FROM = "iso-27001-2022"
TO = "pci-dss-4.0"
SOURCE = "NexusLine curated from the text of ISO/IEC 27001:2022 and PCI DSS v4.0.1"

ROWS = """
4.3      12.5    intersects  0.7   Scope is determined and documented
6.1.2    12.3    intersects  0.7   Risks are assessed
6.1.2    12.3.1  intersects  0.7   Targeted risk analysis follows a method
6.1.3    12.3    related     0.6   Risk treatment
A.5.1    12.1    intersects  0.8   An information security policy, reviewed and communicated
A.5.3    6.5     related     0.6   Separation of duties between production and pre-production
A.5.9    12.5    intersects  0.65  Inventory of in-scope system components
A.5.10   12.2    superset    0.75  Acceptable use covers end-user technology policies
A.5.12   9.4     related     0.6   Media is classified by sensitivity
A.5.14   4.2     related     0.6   Protection of transferred information
A.5.15   7.1     intersects  0.75  Access control policy and processes
A.5.15   7.2     intersects  0.8   Access defined and assigned by need to know
A.5.15   7.2.1   intersects  0.75  An access control model
A.5.15   7.3     intersects  0.7   Access enforced through systems
A.5.16   8.2     intersects  0.8   User identities managed through their life cycle
A.5.16   8.1     related     0.65  Identification processes defined
A.5.17   8.3     intersects  0.8   Authentication factors managed
A.5.18   7.2     intersects  0.75  Access rights assigned and reviewed
A.5.18   8.2     related     0.65  User IDs added, changed and removed
A.5.19   12.8    intersects  0.8   Third-party service provider risk managed
A.5.20   12.8    intersects  0.7   Written agreements with service providers
A.5.20   12.9    related     0.65  Service providers acknowledge responsibility
A.5.22   12.8    intersects  0.7   Service provider compliance monitored
A.5.24   12.10   intersects  0.8   Incident response readiness
A.5.24   12.10.1 intersects  0.8   An incident response plan
A.5.25   12.10   related     0.65  Assessing suspected incidents
A.5.26   12.10   intersects  0.75  Responding to incidents
A.5.27   12.10   related     0.6   The plan is updated from lessons learned
A.5.36   12.4    related     0.6   Compliance with PCI DSS is managed
A.5.37   1.1     related     0.6   Documented procedures for network security controls
A.5.37   2.1     related     0.6   Documented procedures for secure configuration
A.5.37   3.1     related     0.6   Documented procedures for stored account data
A.5.37   4.1     related     0.6   Documented procedures for transmission protection
A.5.37   5.1     related     0.6   Documented procedures for anti-malware
A.5.37   6.1     related     0.6   Documented procedures for secure development
A.5.37   7.1     related     0.6   Documented procedures for access restriction
A.5.37   8.1     related     0.6   Documented procedures for identification
A.5.37   9.1     related     0.6   Documented procedures for physical access
A.5.37   10.1    related     0.6   Documented procedures for logging
A.5.37   11.1    related     0.6   Documented procedures for testing
A.6.1    12.7    equivalent  0.85  Personnel are screened before hire
A.6.3    12.6    intersects  0.85  Security awareness programme
A.6.8    12.10   related     0.6   Reporting security events
A.7.1    9.2     intersects  0.7   Physical entry to the facility
A.7.2    9.2     intersects  0.75  Facility entry controls
A.7.2    9.3     intersects  0.75  Personnel and visitor access
A.7.4    9.2     related     0.65  Monitoring access to sensitive areas
A.7.10   9.4     intersects  0.8   Media secured
A.7.10   9.4.1   intersects  0.75  Media physically secured
A.7.14   9.4     related     0.65  Media destroyed when no longer needed
A.8.1    1.5     related     0.6   Computing devices connecting to untrusted networks
A.8.2    7.2     related     0.65  Privileges assigned by job function
A.8.2    8.6     related     0.6   System and application accounts managed
A.8.3    7.2     intersects  0.7   Access restricted to need to know
A.8.3    7.3     intersects  0.7   Access control systems
A.8.5    8.3     intersects  0.8   Strong authentication
A.8.5    8.3.1   intersects  0.8   All access is authenticated
A.8.5    8.4     intersects  0.75  MFA into the CDE
A.8.5    8.4.2   intersects  0.75  MFA for all CDE access
A.8.5    8.5     related     0.65  MFA systems configured against misuse
A.8.7    5.1     related     0.65  Anti-malware processes defined
A.8.7    5.2     intersects  0.85  Malware prevented or detected
A.8.7    5.2.1   intersects  0.8   Anti-malware deployed
A.8.7    5.3     intersects  0.8   Anti-malware active and monitored
A.8.7    5.3.1   intersects  0.75  Anti-malware kept current
A.8.7    5.4     related     0.65  Anti-phishing
A.8.8    6.3     intersects  0.85  Vulnerabilities identified and addressed
A.8.8    6.3.1   intersects  0.8   Vulnerabilities ranked and managed
A.8.8    6.3.3   intersects  0.8   Security patches applied
A.8.8    11.3    intersects  0.85  Vulnerability scanning
A.8.8    11.3.1  intersects  0.75  Internal vulnerability scans
A.8.8    11.4    related     0.6   Penetration tests find vulnerabilities
A.8.9    2.2     intersects  0.85  System components configured securely
A.8.9    2.2.1   intersects  0.8   Configuration standards
A.8.9    2.2.2   related     0.65  Vendor defaults managed
A.8.9    2.1     related     0.6   Configuration processes defined
A.8.9    1.2     related     0.65  NSC configuration
A.8.9    1.2.1   related     0.6   NSC ruleset standards
A.8.10   3.2.1   related     0.65  Stored data deleted after retention
A.8.10   3.3.1   related     0.6   Sensitive authentication data not retained
A.8.11   3.4     intersects  0.75  PAN display restricted
A.8.11   3.4.1   intersects  0.75  PAN masked when displayed
A.8.15   10.1    related     0.65  Logging processes defined
A.8.15   10.2    intersects  0.85  Audit logs implemented
A.8.15   10.2.1  intersects  0.8   Audit logs enabled
A.8.15   10.3    intersects  0.75  Audit logs protected
A.8.15   10.5    intersects  0.75  Audit log history retained
A.8.16   10.4    intersects  0.75  Audit logs reviewed
A.8.16   10.4.1  intersects  0.7   Daily log review
A.8.16   11.5    intersects  0.7   Intrusions detected
A.8.16   10.7    related     0.65  Security control failures detected
A.8.16   11.6    related     0.6   Payment page changes detected
A.8.17   10.6    equivalent  0.85  Time synchronisation
A.8.20   1.1     related     0.65  Network security control processes
A.8.20   1.2     intersects  0.75  NSCs configured and maintained
A.8.20   1.3     related     0.65  CDE network access restricted
A.8.20   1.4     intersects  0.7   Trusted and untrusted networks controlled
A.8.20   1.5     related     0.6   Dual-connected devices
A.8.20   2.3     related     0.6   Wireless environments
A.8.20   11.2    related     0.6   Wireless access points managed
A.8.21   1.2.5   related     0.6   Approved services, protocols and ports
A.8.22   1.3     intersects  0.75  CDE segmented from other networks
A.8.22   1.3.1   related     0.65  Inbound CDE traffic restricted
A.8.22   1.3.2   related     0.65  Outbound CDE traffic restricted
A.8.22   1.4.1   intersects  0.7   NSCs between trusted and untrusted networks
A.8.24   3.5     intersects  0.7   PAN secured in storage
A.8.24   3.5.1   intersects  0.7   PAN rendered unreadable
A.8.24   3.6     intersects  0.75  Cryptographic keys secured
A.8.24   3.7     intersects  0.75  Key management life cycle
A.8.24   4.2     intersects  0.75  Strong cryptography in transit
A.8.24   4.2.1   intersects  0.7   Strong protocols
A.8.24   2.2.7   related     0.65  Administrative access encrypted
A.8.25   6.1     intersects  0.7   Secure development processes defined
A.8.25   6.2     intersects  0.8   Software developed securely
A.8.25   6.2.1   intersects  0.75  Secure development practices
A.8.26   6.2     related     0.6   Security requirements in development
A.8.26   6.4     related     0.6   Public-facing web applications protected
A.8.28   6.2     intersects  0.7   Coding techniques prevent common attacks
A.8.28   6.2.1   related     0.65  Secure coding practices
A.8.29   6.2     related     0.6   Code reviewed before release
A.8.31   6.5     intersects  0.7   Pre-production separated from production
A.8.32   6.5     intersects  0.85  Changes managed securely
A.8.33   6.5     related     0.6   Live account data not used in pre-production
"""
