"""ISO/IEC 27001:2022 → SBP Cyber Security / Information Security Guidelines.

No published mapping exists. Rows are matched on the content of the library's SBP Cyber
Security clauses against ISO clauses and Annex A controls. Where the SBP clause names one
thing ISO also names as one control (asset inventory, classification, threat
intelligence, access control policy, secure configuration, cryptography, data loss
prevention, lessons learned, contractual security requirements) the row is
``equivalent``; otherwise ``intersects`` or ``related``. SBP clauses with no ISO
counterpart (SBP incident reporting timelines, customer awareness, fraud monitoring,
payment channel security) are deliberately left unmapped or only ``related``.
"""

FROM = "iso-27001-2022"
TO = "sbp-cybersecurity"
SOURCE = "NexusLine curated"

ROWS = """
5.1      CS-1.1   related     0.6   Senior management ownership of cyber risk
5.3      CS-1.4   intersects  0.7   Roles and accountabilities
6.1.2    CS-1.5   related     0.6   Risk acceptance criteria and appetite
6.1.2    CS-2.3   intersects  0.8   Cyber risk assessment
6.1.3    CS-2.7   intersects  0.7   Treatment tracked to acceptable residual risk
7.1      CS-1.9   intersects  0.7   Budget, tools and people
7.2      CS-8.2   related     0.6   Competence of high-risk roles
7.3      CS-8.1   intersects  0.75  Awareness of all staff
8.2      CS-2.3   intersects  0.7   Periodic risk assessment
9.1      CS-1.7   intersects  0.7   Metrics and reporting
9.2.1    CS-1.8   intersects  0.7   Internal audit of the programme
A.5.1    CS-1.2   intersects  0.75  Documented policies
A.5.2    CS-1.3   related     0.6   Security function
A.5.2    CS-1.4   equivalent  0.8   Security roles and responsibilities
A.5.5    CS-5.5   intersects  0.7   Reporting to the regulator
A.5.5    CS-5.6   related     0.6   Notifying authorities
A.5.5    CS-5.10  related     0.65  Coordination with authorities
A.5.6    CS-5.10  intersects  0.7   Sharing with sector bodies
A.5.7    CS-2.4   equivalent  0.85  Threat intelligence
A.5.7    CS-4.8   related     0.6   Intelligence informs threat hunting
A.5.9    CS-2.1   equivalent  0.85  Inventory of information assets with owners
A.5.12   CS-2.2   equivalent  0.85  Classification by criticality and sensitivity
A.5.15   CS-3.1   equivalent  0.85  Access control policy on least privilege and need to know
A.5.15   CS-7.5   related     0.6   Third-party access rules
A.5.16   CS-3.2   intersects  0.75  Identity provisioning and removal
A.5.18   CS-3.2   intersects  0.8   Access granted, revoked and recertified
A.5.19   CS-7.1   intersects  0.8   Third-party security risk managed
A.5.19   CS-7.2   related     0.65  Due diligence on third parties
A.5.19   CS-7.5   related     0.6   Third-party access
A.5.20   CS-7.3   equivalent  0.8   Security requirements in third-party contracts
A.5.20   CS-7.7   related     0.6   Incident notification obligations
A.5.21   CS-7.1   intersects  0.7   Supply chain risk
A.5.21   CS-7.6   related     0.6   Fourth-party risk
A.5.22   CS-7.4   intersects  0.8   Third parties monitored
A.5.24   CS-5.1   intersects  0.8   Incident response policy and plan
A.5.24   CS-5.2   intersects  0.7   Incident response team and roles
A.5.24   CS-5.9   related     0.6   Plan exercised
A.5.25   CS-4.6   intersects  0.75  Events triaged
A.5.25   CS-5.3   intersects  0.8   Incidents classified by severity
A.5.26   CS-5.4   intersects  0.8   Containment and eradication
A.5.26   CS-5.5   related     0.6   Reporting during response
A.5.26   CS-5.6   related     0.6   Notification during response
A.5.27   CS-5.8   equivalent  0.85  Lessons learned and corrective action
A.5.28   CS-5.7   intersects  0.8   Evidence preservation
A.5.29   CS-6.1   intersects  0.7   Maintaining services during disruption
A.5.29   CS-6.5   related     0.6   Security within continuity arrangements
A.5.30   CS-2.8   related     0.6   Critical services and dependencies
A.5.30   CS-6.1   intersects  0.7   Resilience of critical services
A.5.30   CS-6.2   intersects  0.7   Recovery objectives
A.5.30   CS-6.4   intersects  0.7   Recovery tested
A.5.30   CS-6.5   intersects  0.75  Integrated with business continuity
A.5.31   CS-1.6   equivalent  0.8   Legal and regulatory requirements
A.5.34   CS-3.11  related     0.6   Protection of personal data
A.5.35   CS-1.8   intersects  0.75  Independent review
A.6.3    CS-8.1   intersects  0.85  Awareness programme
A.6.3    CS-8.2   intersects  0.75  Role-based training
A.6.7    CS-3.6   related     0.65  Remote access security
A.7.1    CS-3.15  intersects  0.7   Physical perimeter
A.7.2    CS-3.15  intersects  0.7   Physical entry
A.7.5    CS-3.15  intersects  0.7   Environmental protection
A.8.1    CS-3.7   intersects  0.75  Endpoint protection
A.8.2    CS-3.4   intersects  0.85  Privileged access management
A.8.3    CS-3.11  related     0.65  Access to data restricted
A.8.5    CS-3.3   intersects  0.8   Strong and multi-factor authentication
A.8.7    CS-3.7   intersects  0.75  Anti-malware
A.8.7    CS-3.13  related     0.6   Malware in email and web
A.8.8    CS-2.5   intersects  0.8   Vulnerabilities identified
A.8.8    CS-3.8   intersects  0.8   Vulnerabilities remediated by severity
A.8.8    CS-4.9   related     0.6   Testing finds vulnerabilities
A.8.9    CS-3.9   equivalent  0.85  Secure configuration standards
A.8.11   CS-3.11  related     0.6   Masking protects data
A.8.12   CS-3.12  equivalent  0.85  Data loss prevention
A.8.15   CS-4.2   intersects  0.75  Log collection
A.8.15   CS-4.5   intersects  0.8   Log retention and integrity
A.8.16   CS-4.1   intersects  0.7   Security monitoring capability
A.8.16   CS-4.2   intersects  0.7   Log analysis
A.8.16   CS-4.3   intersects  0.8   Continuous monitoring
A.8.16   CS-4.4   related     0.65  Intrusion detection
A.8.18   CS-3.4   related     0.6   Privileged utilities
A.8.20   CS-2.6   related     0.6   Network architecture documented
A.8.20   CS-3.5   intersects  0.8   Network security
A.8.20   CS-3.6   intersects  0.7   Perimeter security
A.8.20   CS-4.4   related     0.6   Network intrusion prevention
A.8.22   CS-3.5   intersects  0.8   Segmentation and secure zones
A.8.23   CS-3.13  intersects  0.7   Web filtering
A.8.24   CS-3.10  equivalent  0.85  Cryptography and key management
A.8.25   CS-3.14  intersects  0.7   Secure development
A.8.26   CS-3.14  intersects  0.75  Application security requirements
A.8.28   CS-3.14  related     0.65  Secure coding
A.8.29   CS-4.9   related     0.6   Security testing
A.8.13   CS-6.3   intersects  0.85  Backups including offline copies
A.8.13   CS-6.4   related     0.65  Restoration tested
"""
