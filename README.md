# Discord Work & Leave Tracker Bot

A comprehensive Discord bot system for managing team member productivity, tracking daily work status, and processing leave requests with hierarchical approval workflows. The bot implements role-based access control, focusing exclusively on active team members while providing automated compliance monitoring and reporting capabilities.

## Table of Contents
- [Project Overview](#project-overview)
- [Core Features](#core-features)
- [System Architecture](#system-architecture)
- [Installation & Setup](#installation--setup)
- [Discord Server Configuration](#discord-server-configuration)
- [Usage Guide](#usage-guide)
- [Technical Implementation](#technical-implementation)
- [Configuration Management](#configuration-management)
- [Data Management](#data-management)
- [Monitoring & Reporting](#monitoring--reporting)
- [Security & Compliance](#security--compliance)
- [Troubleshooting](#troubleshooting)
- [Development & Maintenance](#development--maintenance)

## Project Overview

This Discord bot serves as a comprehensive workforce management system designed for academic or professional teams. It automates daily productivity tracking, manages various types of leave requests, and maintains compliance through an intelligent warning system. The bot operates with role-based filtering, ensuring only active team members (those with the "current-team" role) are monitored and managed.

### Key Objectives
- **Productivity Tracking**: Monitor daily work hours and activities with 32-hour weekly targets
- **Leave Management**: Process three types of leave requests with hierarchical approval workflows
- **Compliance Monitoring**: Automated warning system with probation escalation
- **Team Focus**: Role-based filtering to monitor only active team members
- **Administrative Oversight**: Comprehensive reporting and data export capabilities

## Core Features

### Daily Status Updates
- **Interactive Forms**: Discord modal-based forms for easy data entry
- **Flexible Work Options**: Support for Work From Home (WFH) with adjusted hour requirements
- **Time Validation**: Minimum hour requirements based on day type and work location
- **Late Submission Tracking**: Automatic flagging of backdated submissions
- **Weekly Target Monitoring**: Real-time progress tracking toward 32-hour weekly goals
- **Dynamic Channel Routing**: Automatic posting to appropriate team/year-specific channels

### Leave Management System
Three distinct leave types with tailored workflows:

#### Casual Leave
- **Monthly Allocation**: 2 days per month for regular members
- **Unlimited Access**: Core Members receive unlimited casual leave
- **Auto-approval**: Instant processing within monthly limits
- **Usage Tracking**: Monthly consumption monitoring and rollover prevention

#### Medical Leave
- **Approval Required**: Hierarchical approval process based on role levels
- **Flexible Modes**: Support for both Day-off and Work From Home options
- **Detailed Documentation**: Comprehensive reason requirement for audit trails
- **Priority Processing**: Medical leave receives expedited handling

#### Special Leave
- **Emergency Support**: For exams, family emergencies, and exceptional circumstances
- **Approval Required**: Senior-level approval mandatory
- **Detailed Justification**: Comprehensive reason documentation required
- **Extended Duration**: Support for multi-day special circumstances

### Intelligent Warning System
- **Daily Monitoring**: Automated checks at midnight IST for compliance
- **Role-based Exemptions**: Core Members and 4th-year students exempt
- **Progressive Probation**: 3 warnings trigger 1st Probation, 4+ trigger 2nd Probation
- **Leave Integration**: Approved leave automatically exempts from warnings
- **Monthly Reset**: Warning counters reset monthly for fresh starts

### Advanced Features
- **Performance Caching**: 30-minute role caching with automatic refresh
- **Real-time Updates**: Instant cache updates on role changes
- **CSV Export**: Comprehensive data export with date range filtering
- **Channel Auto-provisioning**: Automatic creation of missing team channels
- **Multi-timezone Support**: IST-based scheduling with UTC conversion

## System Architecture

### Project Structure
```
BOT/
├── src/
│   ├── core/                      # Core business logic
│   │   | 
│   │   ├── user_stats.py         # User data management and statistics
│   │   ├── warnings.py           # Warning system and probation logic
│   │   ├── channel_lookup.py     # Dynamic channel routing system
│   │   ├── current_team_manager.py # Role-based filtering with caching
│   │   └── utils.py              # Shared utility functions
│   ├── ui/                       # User interface components
│   │   ├── forms.py              # Discord modal forms for data input
│   │   └── buttons.py            # Interactive button interfaces
│   ├── data/                     # JSON-based data storage
│   │   ├── users.json            # User submissions and statistics
│   │   ├── pending.json          # Pending leave requests
│   │   ├── warnings.json         # Warning tracking data
│   │   ├── casual_leave.json     # Casual leave history
│   │   └── current_team_cache.json # Role cache storage
│   └── main.py                   # Bot initialization and command handlers
├── .env                          # Environment configuration
└── requirements.txt              # Python dependencies
```

### Data Flow Architecture
1. **User Interaction** → Discord UI (Buttons/Modals)
2. **Validation Layer** → Input sanitization and business rule checking
3. **Business Logic** → Core processing and state management
4. **Data Persistence** → JSON file storage with atomic writes
5. **Channel Distribution** → Dynamic routing to appropriate channels
6. **Cache Management** → Performance optimization and consistency

## Installation & Setup

### Prerequisites
- Python 3.9 or higher
- Discord Bot Token with appropriate permissions
- Discord server with administrative access

### Dependencies
```bash
pip install discord.py python-dotenv
```

### Environment Configuration
Create a `.env` file with the following structure:
```env
# Discord Bot Authentication
DISCORD_BOT_TOKEN=your_bot_token_here

# Channel Configuration
SUPPORT_CHANNEL_ID=1415432843886329988
LEAVE_REQUEST_CHANNEL_ID=1416718401044349038
LEAVE_TRACKING_CHANNEL_ID=1415019014224089147
WARNING_CHANNEL_ID=1416744851457704158

# Role Configuration
CURRENT_TEAM_ROLE_NAME=current-team

# Performance Settings
CACHE_DURATION_MINUTES=30
```

### Bot Initialization
```bash
# Navigate to project directory
cd BOT

# Run the bot
python -m src.main
```

## Discord Server Configuration

### Essential Role Structure
Configure these exact role names in your Discord server:

#### Primary Roles
- **`current-team`**: Primary filtering role - only members with this role are monitored
- **`Core Member`**: Senior role with unlimited leave privileges and auto-approval
- **`Trainee Member`**: Entry-level position equivalent to 1st year
- **`1st_years`, `2nd_years`, `3rd_years`, `4th_years`**: Academic year classifications

#### Team Classification Roles
- **`RedTeam`**: Security and penetration testing team
- **`Android`**: Mobile application development team
- **`BlockChain`**: Blockchain and cryptocurrency development
- **`Mobile`**: General mobile development team

#### Auto-managed Roles
- **`1st Probation`**: Applied automatically after 3 monthly warnings
- **`2nd Probation`**: Applied automatically after 4+ monthly warnings

### Channel Configuration

#### Required Management Channels
Create these channels manually and update IDs in your `.env` file:

1. **Support Channel** (SUPPORT_CHANNEL_ID)
   - Primary bot interface location
   - Houses main interaction buttons
   - Accessible to all current-team members

2. **Leave Request Channel** (LEAVE_REQUEST_CHANNEL_ID)
   - Displays pending leave requests
   - Administrative approval interface
   - Restricted to management personnel

3. **Leave Tracking Channel** (LEAVE_TRACKING_CHANNEL_ID)
   - Logs all leave approvals and denials
   - Audit trail for administrative review
   - Historical record keeping

4. **Warning Channel** (WARNING_CHANNEL_ID)
   - Automated warning notifications
   - Probation status announcements
   - Compliance monitoring alerts

#### Auto-generated Status Channels
The bot automatically creates status update channels following this pattern:
- **Category**: Team name (e.g., "Red Teaming", "Mobile", "Blockchain")
- **Channel**: `{year}-year-status-updates` (e.g., "1st-year-status-updates")

### Bot Permissions
Grant these permissions to your bot role:
- **Text Permissions**: Send Messages, Read Message History, Embed Links
- **Channel Management**: Manage Channels (for auto-provisioning)
- **Role Management**: Manage Roles (for probation system)
- **Advanced**: Use Slash Commands, Manage Messages

## Usage Guide

### For Team Members

#### Daily Status Submission
1. Navigate to the support channel
2. Click "Status Updates" button
3. Select Work From Home option if applicable
4. Complete the modal form:
   - **Date**: DD-MM-YYYY format (allows backdated submissions)
   - **Hours Worked**: Minimum 4 hours (2 for WFH), 6 hours weekends (3 for WFH)
   - **Work Description**: Detailed description of daily activities
   - **Blockers**: Any impediments or challenges faced
5. Submit before 11:59 PM to avoid warnings

#### Leave Request Process
1. Click "Leave Tracking" button in support channel
2. Select appropriate leave type
3. Complete the relevant form:
   - **Casual Leave**: Date range and optional reason
   - **Medical Leave**: Date range, detailed reason, and mode (Day-off/WFH)
   - **Special Leave**: Date range and comprehensive justification
4. Await approval (except casual leave which is auto-approved)

### For Administrators

#### Command Reference
- **`/weekly_report [user] [week_offset]`**: Generate productivity reports
- **`/export_csv [from_date] [to_date]`**: Export team data with date filtering
- **`/refresh_current_team`**: Manually refresh role cache
- **`/config_info`**: Display current bot configuration
- **`/setup_support_channel`**: Initialize main interface (owner only)

#### Leave Approval Process
1. Monitor leave request channel for new requests
2. Review request details and member hierarchy
3. Use approval buttons:
   - **Approve**: Grant leave request
   - **Deny**: Reject with automatic notification
   - **Thread**: Create discussion thread for clarification

## Technical Implementation

### Role-based Hierarchy System
The bot implements a sophisticated hierarchy for leave approvals:
- **Level 1** (1st years): Can be approved by levels 2, 3, 4, 5
- **Level 2** (2nd years): Can be approved by levels 3, 4, 5
- **Level 3** (3rd years): Can be approved by levels 4, 5
- **Level 4** (4th years): Can be approved by level 5 only
- **Level 5** (Core Members): Auto-approved, no manual approval needed

### Validation Framework
Comprehensive input validation includes:
- **Date Formats**: Strict DD-MM-YYYY validation with logical checks
- **Hour Requirements**: Dynamic minimums based on day type and work mode
- **Text Content**: Length limits and meaningful content verification
- **Role Prerequisites**: Automatic verification of required team/year roles

### Performance Optimization
- **Intelligent Caching**: 30-minute cache duration with real-time updates
- **Atomic File Operations**: Temporary file writes to prevent corruption
- **Batch Processing**: Efficient bulk operations for background tasks
- **Memory Management**: Careful resource usage for long-running processes

### Background Task Automation
- **Daily Warning Check**: 12:00 AM IST automated compliance verification
- **Reminder System**: 11:59 PM IST proactive submission reminders
- **Cache Maintenance**: Automatic cleanup and refresh operations
- **Data Archival**: Periodic cleanup of old requests and temporary files

## Configuration Management

### Environment Variables
All configuration is externalized through environment variables:
- **Channel IDs**: Easy reconfiguration without code changes
- **Role Names**: Customizable role name mapping
- **Performance Tuning**: Adjustable cache duration and timeouts
- **Feature Flags**: Optional feature enable/disable capability

### Multi-environment Support
- **Development**: Separate channel IDs for testing
- **Production**: Live server configuration
- **Staging**: Intermediate testing environment
- **Local**: Developer-specific settings

## Data Management

### Storage Architecture
- **JSON Files**: Lightweight, human-readable data storage
- **Atomic Writes**: Corruption prevention through temporary files
- **Backup Integration**: Automatic backup creation during critical operations
- **Schema Validation**: Data integrity checks and migration support

### Data Export Capabilities
- **CSV Generation**: Structured export with customizable date ranges
- **Filtering Options**: User-specific, team-specific, or date-range filtering
- **Administrative Reports**: Comprehensive productivity and compliance reports
- **Historical Analysis**: Long-term trend analysis and pattern recognition

### Privacy and Retention
- **Data Minimization**: Only necessary information collected
- **Retention Policies**: Automatic cleanup of old temporary data
- **Access Control**: Role-based access to sensitive information
- **Audit Trails**: Complete logging of administrative actions

## Monitoring & Reporting

### Real-time Monitoring
- **Console Logging**: Detailed operation logs for troubleshooting
- **Performance Metrics**: Cache hit rates and operation timing
- **Error Tracking**: Comprehensive exception handling and logging
- **Health Checks**: Automatic validation of critical configurations

### Reporting Capabilities
- **Weekly Productivity**: Individual and team performance summaries
- **Compliance Reports**: Warning trends and probation statistics
- **Leave Utilization**: Usage patterns and capacity planning
- **Activity Exports**: Historical data for external analysis

## Security & Compliance

### Access Control
- **Role-based Filtering**: Comprehensive permission system
- **Hierarchical Approvals**: Multi-level approval workflows
- **Self-service Prevention**: Users cannot approve their own requests
- **Administrative Oversight**: Complete audit trails for all actions

### Data Protection
- **Input Sanitization**: Comprehensive validation and sanitization
- **Injection Prevention**: Protection against malicious input
- **Secure Storage**: Encrypted environment variable storage
- **Access Logging**: Complete audit trails for sensitive operations

### Compliance Features
- **Automatic Enforcement**: Consistent application of business rules
- **Exception Handling**: Proper handling of edge cases and errors
- **Documentation**: Comprehensive logging for regulatory compliance
- **Privacy Controls**: Minimal data collection and appropriate retention

## Troubleshooting

### Common Issues

#### Configuration Problems
- **Missing Environment Variables**: Verify all required variables in `.env`
- **Invalid Channel IDs**: Use `/config_info` command to verify configuration
- **Role Name Mismatches**: Ensure exact role name matches in server

#### Performance Issues
- **Cache Problems**: Use `/refresh_current_team` to force cache refresh
- **Slow Responses**: Check console logs for performance bottlenecks
- **Memory Usage**: Monitor long-running processes for memory leaks

#### Data Integrity
- **Corrupted JSON**: Bot automatically creates backups and recovers
- **Missing Submissions**: Check user role assignments and channel routing
- **Synchronization Issues**: Verify atomic write operations in logs



