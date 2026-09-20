"""ISO/IEC 27001:2022 → NIST SP 800-53 Rev. 5.

NIST publishes a mapping between SP 800-53 Rev. 5 and ISO/IEC 27001 (built against the
2013 Annex A). These rows carry it to the 2022 Annex A through the ISO/IEC 27002:2022
Annex B correspondence (A.9.4.2 → A.8.5, A.12.3.1 → A.8.13, A.12.4.4 → A.8.17 ...) and
add the 2022 controls that had no 2013 predecessor (A.5.7 threat intelligence, A.5.23
cloud services, A.8.9 configuration management, A.8.10-A.8.12 deletion, masking and
leakage prevention, A.8.16 monitoring, A.8.23 web filtering, A.8.28 secure coding) by
their content. NIST marks most of its rows as partial; most rows here are therefore
``intersects``, and ``equivalent`` is kept for the few one-to-one pairs.
"""

FROM = "iso-27001-2022"
TO = "nist-800-53-r5"
SOURCE = "NIST SP 800-53 Rev. 5 to ISO/IEC 27001 mapping, carried to 27001:2022 via ISO/IEC 27002:2022 Annex B"

ROWS = """
# ---- clauses 4-10
5.1      PM-2   related     0.6   Senior leadership of the security programme
5.2      PM-1   intersects  0.7   Programme plan and policy
5.3      PM-2   related     0.6   Programme leadership role
5.3      PM-29  related     0.6   Risk management roles
6.1.2    RA-3   intersects  0.8   Risk assessment
6.1.3    RA-7   intersects  0.75  Risk response
6.1.1    PM-9   related     0.6   Risk management strategy
7.1      PM-3   intersects  0.75  Security resources
7.2      PM-13  related     0.6   Security workforce competence
7.2      AT-3   related     0.6   Role-based training builds competence
7.3      AT-2   intersects  0.75  Awareness
8.2      RA-3   related     0.65  Risk assessments are performed
8.3      RA-7   related     0.65  Risk responses are implemented
9.1      PM-6   intersects  0.7   Measures of performance
9.1      CA-7   related     0.65  Continuous monitoring
9.2.1    CA-2   related     0.65  Control assessments
9.2.2    CA-2   related     0.6   Assessment planning
10.2     CA-5   intersects  0.7   Plans of action for deficiencies
10.2     PM-4   related     0.65  POA&M process
# ---- Annex A 5 organisational
A.5.1    PM-1   intersects  0.8   Security policy at programme level
A.5.2    PM-2   related     0.65  Security leadership role
A.5.2    PS-9   related     0.6   Security responsibilities in position descriptions
A.5.3    AC-5   equivalent  0.85  Separation of duties
A.5.4    PL-4   related     0.6   Personnel follow the rules of behaviour
A.5.5    IR-6   related     0.65  Reporting to authorities
A.5.6    PM-15  equivalent  0.8   Contact with security groups and associations
A.5.6    SI-5   related     0.6   Advisories from external organisations
A.5.7    PM-16  intersects  0.8   Threat awareness programme
A.5.7    SI-5   intersects  0.75  Security alerts and advisories
A.5.7    RA-10  related     0.6   Threat hunting uses threat intelligence
A.5.8    SA-3   intersects  0.7   Security in the development life cycle of projects
A.5.8    SA-8   related     0.6   Engineering principles in projects
A.5.9    CM-8   intersects  0.85  System component inventory
A.5.9    PM-5   related     0.65  System inventory
A.5.10   PL-4   intersects  0.75  Rules of behaviour
A.5.10   MP-7   related     0.6   Media use
A.5.10   AC-20  related     0.6   Use of external systems
A.5.11   PS-4   intersects  0.7   Assets returned at termination
A.5.11   PS-5   related     0.6   Assets returned on transfer
A.5.12   RA-2   intersects  0.8   Security categorisation
A.5.13   MP-3   intersects  0.75  Media marking
A.5.13   AC-16  related     0.65  Security attributes
A.5.13   PE-22  related     0.6   Component marking
A.5.14   CA-3   intersects  0.7   Information exchange agreements
A.5.14   AC-4   intersects  0.7   Information flow enforcement
A.5.14   SC-8   related     0.6   Transmission protection
A.5.14   AC-21  related     0.6   Information sharing
A.5.15   AC-1   intersects  0.75  Access control policy
A.5.15   AC-3   intersects  0.8   Access enforcement
A.5.15   AC-6   related     0.65  Least privilege
A.5.16   IA-4   intersects  0.8   Identifier management
A.5.16   AC-2   intersects  0.8   Account management
A.5.17   IA-5   intersects  0.85  Authenticator management
A.5.18   AC-2   intersects  0.8   Access rights granted, reviewed and removed
A.5.18   AC-6   related     0.6   Privileges are reviewed
A.5.18   PS-4   related     0.6   Access removed at termination
A.5.18   PS-5   related     0.6   Access adjusted on transfer
A.5.19   SA-9   intersects  0.7   External system services
A.5.19   SR-2   related     0.65  Supply chain risk management plan
A.5.19   SR-3   related     0.65  Supply chain controls
A.5.19   PM-30  related     0.6   Supply chain strategy
A.5.20   SA-4   intersects  0.75  Security requirements in acquisition contracts
A.5.20   SA-9   intersects  0.7   Requirements for external services
A.5.20   SR-3   related     0.6   Supply chain requirements
A.5.21   SR-3   intersects  0.75  Supply chain controls and processes
A.5.21   SR-5   related     0.65  Acquisition strategies
A.5.21   SR-4   related     0.6   Provenance
A.5.21   SR-11  related     0.6   Component authenticity
A.5.22   SA-9   intersects  0.75  External services are monitored
A.5.22   SR-6   intersects  0.7   Supplier reviews
A.5.23   SA-9   intersects  0.65  Cloud services are external services
A.5.23   AC-20  related     0.6   Use of external systems
A.5.24   IR-8   intersects  0.8   Incident response plan
A.5.24   IR-1   related     0.65  Incident response policy and procedures
A.5.25   IR-4   intersects  0.7   Events are analysed in incident handling
A.5.25   IR-5   related     0.6   Incident monitoring
A.5.26   IR-4   intersects  0.8   Incident handling
A.5.27   IR-4   related     0.65  Lessons learned are incorporated
A.5.28   IR-4   related     0.6   Evidence in incident handling
A.5.29   CP-2   intersects  0.65  Security is maintained through disruption
A.5.29   CP-13  related     0.6   Alternative security mechanisms
A.5.30   CP-2   intersects  0.75  Contingency plan
A.5.30   CP-4   intersects  0.7   Contingency plan testing
A.5.30   CP-7   related     0.65  Alternate processing site
A.5.30   CP-10  related     0.6   Recovery and reconstitution
A.5.32   CM-10  intersects  0.75  Software usage restrictions protect licences
A.5.33   SI-12  intersects  0.7   Information retention
A.5.33   AU-11  related     0.6   Audit record retention
A.5.33   AU-9   related     0.6   Protection of audit information
A.5.34   PM-18  intersects  0.7   Privacy programme
A.5.34   PT-2   related     0.65  Authority to process PII
A.5.34   PT-3   related     0.65  Processing purposes
A.5.34   RA-8   related     0.6   Privacy impact assessments
A.5.35   CA-2   intersects  0.7   Independent control assessments
A.5.36   CA-2   related     0.6   Compliance is assessed
A.5.36   CA-7   related     0.6   Continuous monitoring of compliance
# ---- Annex A 6 people
A.6.1    PS-3   equivalent  0.85  Personnel screening
A.6.2    PS-6   intersects  0.75  Access agreements
A.6.2    PL-4   related     0.65  Rules of behaviour
A.6.3    AT-2   intersects  0.85  Awareness training
A.6.3    AT-3   intersects  0.75  Role-based training
A.6.4    PS-8   equivalent  0.85  Personnel sanctions
A.6.5    PS-4   intersects  0.75  Personnel termination
A.6.5    PS-5   intersects  0.75  Personnel transfer
A.6.5    PS-6   related     0.6   Agreements that survive employment
A.6.6    PS-6   intersects  0.75  Non-disclosure agreements
A.6.7    AC-17  intersects  0.7   Remote access
A.6.7    PE-17  intersects  0.7   Alternate work site
A.6.8    IR-6   intersects  0.75  Incident reporting
# ---- Annex A 7 physical
A.7.1    PE-3   intersects  0.75  Physical access control at the perimeter
A.7.2    PE-2   intersects  0.75  Physical access authorisations
A.7.2    PE-3   intersects  0.75  Physical access control
A.7.2    PE-8   related     0.65  Visitor access records
A.7.3    PE-3   intersects  0.7   Securing rooms and facilities
A.7.3    PE-5   related     0.6   Access control for output devices
A.7.4    PE-6   equivalent  0.85  Monitoring physical access
A.7.5    PE-13  intersects  0.75  Fire protection
A.7.5    PE-14  intersects  0.7   Environmental controls
A.7.5    PE-15  intersects  0.7   Water damage protection
A.7.5    PE-23  related     0.6   Facility location
A.7.6    PE-3   related     0.6   Working in secure areas
A.7.7    AC-11  intersects  0.7   Device lock (clear screen)
A.7.8    PE-18  intersects  0.8   Location of system components
A.7.9    MP-5   intersects  0.7   Media transport off premises
A.7.9    AC-19  related     0.6   Mobile devices off premises
A.7.9    PE-17  related     0.6   Alternate work site
A.7.10   MP-2   intersects  0.7   Media access
A.7.10   MP-4   intersects  0.75  Media storage
A.7.10   MP-5   intersects  0.7   Media transport
A.7.10   MP-7   intersects  0.7   Media use
A.7.10   MP-6   related     0.65  Media sanitisation
A.7.11   PE-11  intersects  0.75  Emergency power
A.7.11   PE-9   intersects  0.7   Power equipment
A.7.11   PE-12  related     0.6   Emergency lighting
A.7.12   PE-4   intersects  0.75  Access control for transmission cabling
A.7.12   PE-9   intersects  0.75  Power cabling protection
A.7.13   MA-2   intersects  0.8   Controlled maintenance
A.7.13   MA-5   related     0.6   Maintenance personnel
A.7.13   MA-6   related     0.6   Timely maintenance
A.7.14   MP-6   intersects  0.8   Sanitisation before disposal or re-use
A.7.14   SR-12  related     0.6   Component disposal
# ---- Annex A 8 technological
A.8.1    AC-19  intersects  0.75  Mobile and endpoint devices
A.8.1    AC-11  related     0.6   Device lock
A.8.2    AC-6   intersects  0.8   Privileged accounts under least privilege
A.8.2    AC-2   related     0.65  Privileged account management
A.8.3    AC-3   intersects  0.85  Access enforcement
A.8.3    AC-6   related     0.6   Least privilege
A.8.4    CM-5   intersects  0.7   Access restrictions for change
A.8.4    AC-3   related     0.6   Access enforcement on source code
A.8.4    SA-10  related     0.6   Developer configuration management
A.8.5    IA-2   intersects  0.85  Identification and authentication of users
A.8.5    IA-8   intersects  0.7   Authentication of non-organisational users
A.8.5    AC-7   intersects  0.7   Unsuccessful logon attempts
A.8.5    AC-8   related     0.6   System use notification
A.8.5    IA-6   related     0.6   Authentication feedback
A.8.5    AC-9   related     0.55  Previous logon notification
A.8.6    SC-6   related     0.6   Resource availability
A.8.6    AU-4   related     0.6   Log storage capacity
A.8.6    CP-2   related     0.6   Capacity planning
A.8.7    SI-3   equivalent  0.85  Malicious code protection
A.8.7    SI-8   related     0.6   Spam protection
A.8.8    RA-5   intersects  0.85  Vulnerability monitoring and scanning
A.8.8    SI-2   intersects  0.85  Flaw remediation
A.8.8    SI-5   related     0.6   Advisories on vulnerabilities
A.8.9    CM-2   intersects  0.85  Baseline configuration
A.8.9    CM-6   intersects  0.85  Configuration settings
A.8.9    CM-9   intersects  0.75  Configuration management plan
A.8.9    CM-3   related     0.65  Configuration change control
A.8.10   MP-6   intersects  0.7   Sanitisation deletes information
A.8.10   SI-12  related     0.65  Information disposal at end of retention
A.8.11   SI-19  intersects  0.7   De-identification
A.8.11   PM-25  related     0.6   Minimising PII in testing and training
A.8.12   AC-4   intersects  0.7   Information flow enforcement
A.8.12   AU-13  intersects  0.65  Monitoring for information disclosure
A.8.12   SC-7   related     0.65  Boundary protection against exfiltration
A.8.12   SI-4   related     0.6   System monitoring
A.8.13   CP-9   equivalent  0.9   System backup
A.8.14   CP-7   intersects  0.75  Alternate processing site
A.8.14   CP-6   related     0.65  Alternate storage site
A.8.14   CP-8   related     0.6   Alternate telecommunications
A.8.14   SC-36  related     0.6   Distributed processing and storage
A.8.15   AU-2   intersects  0.85  Event logging
A.8.15   AU-12  intersects  0.8   Audit record generation
A.8.15   AU-3   intersects  0.75  Content of audit records
A.8.15   AU-9   intersects  0.75  Protection of audit information
A.8.15   AU-11  intersects  0.7   Audit record retention
A.8.16   SI-4   intersects  0.85  System monitoring
A.8.16   AU-6   intersects  0.75  Audit review and analysis
A.8.16   IR-5   related     0.6   Incident monitoring
A.8.17   AU-8   equivalent  0.8   Time stamps from synchronised clocks
A.8.17   SC-45  equivalent  0.85  System time synchronisation
A.8.18   AC-6   intersects  0.7   Privileged functions restricted
A.8.18   CM-7   intersects  0.65  Least functionality
A.8.19   CM-11  intersects  0.8   User-installed software
A.8.19   CM-7   related     0.65  Least functionality
A.8.19   CM-5   related     0.6   Access restrictions for change
A.8.20   SC-7   intersects  0.8   Boundary protection
A.8.20   AC-4   related     0.65  Information flow enforcement
A.8.20   AC-17  related     0.6   Remote access
A.8.20   AC-18  related     0.6   Wireless access
A.8.20   SC-8   related     0.6   Transmission protection
A.8.21   SA-9   intersects  0.65  Network services from providers
A.8.21   SC-7   related     0.6   Boundary protection
A.8.21   CA-3   related     0.6   Information exchange agreements
A.8.22   SC-7   intersects  0.8   Subnetworks for publicly accessible components
A.8.22   AC-4   intersects  0.7   Flow control between segments
A.8.22   SC-32  related     0.65  System partitioning
A.8.23   SC-7   related     0.6   Proxy routing and filtering
A.8.24   SC-12  intersects  0.85  Cryptographic key management
A.8.24   SC-13  intersects  0.85  Cryptographic protection
A.8.24   SC-17  related     0.65  PKI certificates
A.8.24   SC-28  related     0.6   Protection at rest
A.8.24   SC-8   related     0.6   Protection in transit
A.8.25   SA-3   intersects  0.85  System development life cycle
A.8.25   SA-15  intersects  0.75  Development process and standards
A.8.25   SA-8   intersects  0.7   Engineering principles
A.8.26   SA-4   intersects  0.7   Security requirements in acquisition
A.8.26   SA-8   related     0.6   Security engineering
A.8.27   SA-8   equivalent  0.8   Security engineering principles
A.8.27   PL-8   intersects  0.75  Security architecture
A.8.27   SA-17  related     0.65  Developer security architecture
A.8.28   SA-15  intersects  0.7   Development standards include secure coding
A.8.28   SA-11  intersects  0.65  Developer testing of code
A.8.28   SI-10  related     0.65  Input validation
A.8.29   SA-11  intersects  0.8   Developer testing and evaluation
A.8.29   CA-2   related     0.6   Control assessment before acceptance
A.8.29   CA-8   related     0.6   Penetration testing
A.8.30   SA-4   intersects  0.7   Acquisition of developed systems
A.8.30   SA-9   related     0.6   External development services
A.8.30   SA-11  related     0.6   Developer testing
A.8.30   SA-15  related     0.6   Developer process
A.8.31   SA-3   related     0.65  Pre-production environments
A.8.31   CM-4   related     0.6   Separate test environments
A.8.32   CM-3   intersects  0.85  Configuration change control
A.8.32   CM-4   intersects  0.75  Impact analysis
A.8.32   CM-5   related     0.6   Access restrictions for change
A.8.32   SA-10  related     0.6   Developer configuration management
A.8.33   PM-25  intersects  0.7   PII in testing
A.8.33   SA-3   related     0.6   Use of live data in development
A.8.34   CA-2   related     0.55  Assessments that touch operational systems
"""
