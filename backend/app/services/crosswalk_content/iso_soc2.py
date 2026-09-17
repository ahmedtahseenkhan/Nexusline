"""ISO/IEC 27001:2022 → SOC 2 Trust Services Criteria (2017, revised points of focus).

The AICPA publishes a mapping between the Trust Services Criteria and ISO/IEC 27001.
Criteria are broad and describe what an entity's controls achieve, so rows are
``intersects`` where the ISO control meets a material part of the criterion and
``related`` where it contributes. ``equivalent`` once (A.8.6 capacity management and
A1.1). The privacy criteria have no single Annex A control; A.5.34 is related to the
main ones.
"""

FROM = "iso-27001-2022"
TO = "soc-2-2017"
SOURCE = "NexusLine curated; aligned with the AICPA Trust Services Criteria mapping to ISO/IEC 27001"

ROWS = """
5.1      CC1.2   related     0.6   Top management and board oversight
5.3      CC1.3   intersects  0.75  Structures, reporting lines, authorities and responsibilities
7.2      CC1.4   intersects  0.75  Competence of personnel
7.4      CC2.2   intersects  0.7   Internal communication of security information
7.4      CC2.3   intersects  0.7   External communication
6.2      CC3.1   intersects  0.7   Objectives specified to identify risk
6.1.2    CC3.2   intersects  0.8   Risks identified and analysed
6.1.2    CC3.3   related     0.6   Fraud risk considered in risk assessment
8.2      CC3.2   related     0.65  Risk assessments performed
6.3      CC3.4   related     0.65  Significant changes identified and assessed
9.1      CC4.1   intersects  0.7   Ongoing evaluation of controls
9.2.1    CC4.1   intersects  0.7   Separate evaluations by internal audit
9.3.3    CC4.2   related     0.6   Management acts on review results
10.2     CC4.2   intersects  0.7   Deficiencies communicated and corrected
6.1.3    CC5.1   intersects  0.7   Controls selected to mitigate risk
5.2      CC5.3   related     0.6   Policy sets expectations
A.5.1    CC5.3   intersects  0.75  Policies establish what is expected
A.5.2    CC1.3   intersects  0.75  Security roles and responsibilities
A.5.3    CC6.3   related     0.65  Segregation of duties in access
A.5.5    CC2.3   related     0.6   Communication with authorities
A.5.9    CC6.1   related     0.6   Information assets identified for protection
A.5.12   C1.1    intersects  0.75  Confidential information identified
A.5.14   CC6.7   intersects  0.75  Information protected during transmission
A.5.15   CC6.1   intersects  0.8   Logical access security
A.5.16   CC6.2   intersects  0.75  Users registered and authorised
A.5.18   CC6.2   intersects  0.75  Access granted and removed
A.5.18   CC6.3   intersects  0.75  Access modified and reviewed by role
A.5.19   CC9.2   intersects  0.8   Vendor and business partner risk
A.5.20   CC9.2   intersects  0.7   Vendor commitments in agreements
A.5.22   CC9.2   intersects  0.7   Vendor performance monitored
A.5.24   CC7.4   intersects  0.75  Incident response programme
A.5.25   CC7.3   intersects  0.8   Security events evaluated
A.5.26   CC7.4   intersects  0.8   Incidents responded to
A.5.27   CC7.5   related     0.65  Learning from incidents in recovery
A.5.28   CC7.4   related     0.6   Evidence in incident response
A.5.29   CC9.1   related     0.65  Business disruption risk
A.5.30   CC9.1   intersects  0.7   Business disruption risk mitigated
A.5.30   CC7.5   related     0.6   Recovery from incidents
A.5.30   A1.3    intersects  0.7   Recovery plans tested
A.5.33   P4.2    related     0.6   Retention of records
A.5.34   P1.1    related     0.55  Privacy notice
A.5.34   P4.1    related     0.55  Use of personal information limited
A.5.34   P6.6    related     0.55  Breach notification
A.5.35   CC4.1   intersects  0.7   Independent evaluation
A.5.36   CC4.1   related     0.6   Compliance evaluations
A.5.37   CC5.3   related     0.6   Procedures put policies into action
A.6.1    CC1.4   related     0.65  Candidates screened
A.6.3    CC2.2   related     0.65  Responsibilities communicated through training
A.6.4    CC1.5   intersects  0.7   Individuals held accountable
A.6.8    CC2.2   related     0.6   Channels to report security matters
A.7.1    CC6.4   intersects  0.7   Physical perimeters restrict access
A.7.2    CC6.4   intersects  0.75  Physical access restricted
A.7.3    CC6.4   related     0.65  Rooms and facilities secured
A.7.4    CC7.2   related     0.6   Physical monitoring for anomalies
A.7.5    A1.2    intersects  0.7   Environmental protections
A.7.10   CC6.7   intersects  0.7   Information on media protected
A.7.11   A1.2    related     0.6   Supporting utilities
A.7.14   CC6.5   intersects  0.75  Assets decommissioned securely
A.7.14   C1.2    related     0.65  Confidential information disposed of with equipment
A.8.2    CC6.3   intersects  0.7   Privileged access by role
A.8.3    CC6.1   related     0.65  Access to information restricted
A.8.5    CC6.1   intersects  0.7   Authentication in the access architecture
A.8.5    CC6.6   related     0.6   Authentication for external access
A.8.6    A1.1    equivalent  0.8   Capacity managed to meet objectives
A.8.7    CC6.8   intersects  0.75  Malicious software prevented or detected
A.8.8    CC7.1   intersects  0.75  Vulnerabilities detected and monitored
A.8.9    CC7.1   intersects  0.7   Configuration changes monitored
A.8.9    CC8.1   related     0.6   Configuration change control
A.8.10   CC6.5   related     0.65  Data removed before disposal
A.8.10   C1.2    intersects  0.75  Confidential information disposed of
A.8.10   P4.3    related     0.6   Personal information disposed of
A.8.12   CC6.7   related     0.65  Leakage of information prevented
A.8.13   A1.2    intersects  0.75  Data backup
A.8.13   A1.3    related     0.6   Backup restoration tested
A.8.14   A1.2    intersects  0.7   Recovery infrastructure
A.8.15   CC7.2   related     0.65  Logs support anomaly monitoring
A.8.16   CC7.2   intersects  0.8   System components monitored for anomalies
A.8.19   CC6.8   intersects  0.75  Unauthorised software prevented
A.8.20   CC6.6   intersects  0.75  Boundary protection against external threats
A.8.22   CC6.1   related     0.6   Network segmentation in the access architecture
A.8.22   CC6.6   related     0.6   Segmentation limits external threats
A.8.24   CC6.1   related     0.65  Encryption in the access architecture
A.8.24   CC6.7   related     0.65  Encryption in transmission
A.8.25   CC8.1   related     0.6   Development follows authorised change
A.8.29   CC8.1   related     0.6   Changes tested before release
A.8.32   CC8.1   intersects  0.85  Changes authorised, tested and approved
"""
