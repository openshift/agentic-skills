"""
Root Cause Analyzer (YAML only) Sub-Agent

This module performs root cause analysis on YAML data extracted by the Data Analyzer.
"""

import json
from typing import Dict, List, Optional, Any


class RootCauseAnalyzerYAML:
    """
    Analyzes YAML data to identify root causes of issues.
    """
    
    def __init__(self):
        """Initialize Root Cause Analyzer"""
        pass
    
    def analyze(self, data_analyzer_results: Dict) -> Dict:
        """
        Perform root cause analysis on YAML data.
        
        Parameters:
        -----------
        data_analyzer_results : dict
            Results from Data Analyzer containing analyzed YAML files
            
        Returns:
        --------
        dict : Root cause analysis results containing:
            - root_causes: List of identified root causes
            - contributing_factors: List of contributing factors
            - evidence: Evidence supporting the analysis
            - confidence: Confidence level of the analysis
            - recommendations: Recommended actions
        """
        print("\n[Root Cause Analyzer] Starting YAML root cause analysis...")
        
        analysis = {
            'root_causes': [],
            'contributing_factors': [],
            'evidence': [],
            'confidence': 'medium',
            'recommendations': [],
            'analysis_summary': ''
        }
        
        # Extract YAML data
        yaml_files_data = {}
        for file_path, file_data in data_analyzer_results.get('data', {}).items():
            if file_data.get('file_type') == 'yaml':
                yaml_files_data[file_path] = file_data
        
        if not yaml_files_data:
            analysis['root_causes'].append({
                'type': 'insufficient_data',
                'description': 'No YAML files were successfully analyzed',
                'severity': 'high'
            })
            analysis['confidence'] = 'low'
            return analysis
        
        print(f"[Root Cause Analyzer] Analyzing {len(yaml_files_data)} YAML files...")
        
        # Analyze each YAML file
        for file_path, file_data in yaml_files_data.items():
            file_analysis = self._analyze_yaml_file(file_path, file_data)
            
            # Merge findings
            if file_analysis.get('root_causes'):
                analysis['root_causes'].extend(file_analysis['root_causes'])
            if file_analysis.get('contributing_factors'):
                analysis['contributing_factors'].extend(file_analysis['contributing_factors'])
            if file_analysis.get('evidence'):
                analysis['evidence'].extend(file_analysis['evidence'])
            if file_analysis.get('recommendations'):
                analysis['recommendations'].extend(file_analysis['recommendations'])
        
        # Deduplicate and prioritize
        analysis = self._prioritize_findings(analysis)
        
        # Generate summary
        analysis['analysis_summary'] = self._generate_summary(analysis)
        
        print(f"[Root Cause Analyzer] Analysis complete:")
        print(f"  - Root causes identified: {len(analysis['root_causes'])}")
        print(f"  - Contributing factors: {len(analysis['contributing_factors'])}")
        print(f"  - Evidence items: {len(analysis['evidence'])}")
        
        return analysis
    
    def _analyze_yaml_file(self, file_path: str, file_data: Dict) -> Dict:
        """Analyze a single YAML file for root causes"""
        findings = {
            'root_causes': [],
            'contributing_factors': [],
            'evidence': [],
            'recommendations': []
        }
        
        raw_data = file_data.get('raw_data', {})
        metadata = file_data.get('metadata', {})
        kind = metadata.get('kind', '')
        
        # Analyze based on Kubernetes resource type
        if kind == 'Pod':
            pod_analysis = self._analyze_pod(raw_data, file_path)
            findings.update(pod_analysis)
        elif kind == 'Event':
            event_analysis = self._analyze_event(raw_data, file_path)
            findings.update(event_analysis)
        elif kind in ['Service', 'ConfigMap', 'Secret']:
            config_analysis = self._analyze_config_resource(raw_data, file_path, kind)
            findings.update(config_analysis)
        else:
            # Generic analysis
            generic_analysis = self._analyze_generic(raw_data, file_path)
            findings.update(generic_analysis)
        
        return findings
    
    def _analyze_pod(self, pod_data: Dict, file_path: str) -> Dict:
        """Analyze Pod YAML for issues"""
        findings = {
            'root_causes': [],
            'contributing_factors': [],
            'evidence': [],
            'recommendations': []
        }
        
        # Check pod status
        status = pod_data.get('status', {})
        phase = status.get('phase', '')
        
        if phase not in ['Running', 'Succeeded']:
            findings['root_causes'].append({
                'type': 'pod_state',
                'description': f'Pod is in {phase} state',
                'severity': 'high',
                'file': file_path
            })
            findings['evidence'].append({
                'type': 'pod_phase',
                'value': phase,
                'file': file_path
            })
        
        # Check container statuses
        container_statuses = status.get('containerStatuses', [])
        for container_status in container_statuses:
            state = container_status.get('state', {})
            
            # Check for waiting state
            if 'waiting' in state:
                reason = state['waiting'].get('reason', '')
                message = state['waiting'].get('message', '')
                findings['root_causes'].append({
                    'type': 'container_waiting',
                    'description': f'Container {container_status.get("name")} is waiting: {reason}',
                    'details': message,
                    'severity': 'high',
                    'file': file_path
                })
            
            # Check for terminated state
            if 'terminated' in state:
                reason = state['terminated'].get('reason', '')
                exit_code = state['terminated'].get('exitCode', 0)
                if exit_code != 0:
                    findings['root_causes'].append({
                        'type': 'container_terminated',
                        'description': f'Container {container_status.get("name")} terminated with exit code {exit_code}',
                        'reason': reason,
                        'severity': 'high',
                        'file': file_path
                    })
        
        # Check conditions
        conditions = status.get('conditions', [])
        for condition in conditions:
            if condition.get('type') == 'Ready' and condition.get('status') != 'True':
                findings['root_causes'].append({
                    'type': 'pod_not_ready',
                    'description': 'Pod is not in Ready state',
                    'reason': condition.get('reason', ''),
                    'message': condition.get('message', ''),
                    'severity': 'high',
                    'file': file_path
                })
        
        # Check resource requests/limits
        spec = pod_data.get('spec', {})
        containers = spec.get('containers', [])
        for container in containers:
            resources = container.get('resources', {})
            if not resources.get('requests') and not resources.get('limits'):
                findings['contributing_factors'].append({
                    'type': 'missing_resource_limits',
                    'description': f'Container {container.get("name")} has no resource requests/limits',
                    'severity': 'medium',
                    'file': file_path
                })
        
        return findings
    
    def _analyze_event(self, event_data: Dict, file_path: str) -> Dict:
        """Analyze Event YAML for issues"""
        findings = {
            'root_causes': [],
            'contributing_factors': [],
            'evidence': [],
            'recommendations': []
        }
        
        # Events are typically lists
        if isinstance(event_data, list):
            events = event_data
        elif isinstance(event_data, dict) and 'items' in event_data:
            events = event_data['items']
        else:
            events = [event_data]
        
        # Analyze events
        error_events = []
        warning_events = []
        
        for event in events:
            if isinstance(event, dict):
                event_type = event.get('type', '')
                reason = event.get('reason', '')
                message = event.get('message', '')
                
                if event_type == 'Warning':
                    warning_events.append({
                        'reason': reason,
                        'message': message,
                        'count': event.get('count', 1)
                    })
                elif 'Error' in reason or 'Failed' in reason:
                    error_events.append({
                        'reason': reason,
                        'message': message,
                        'count': event.get('count', 1)
                    })
        
        # Add findings
        if error_events:
            for error in error_events[:5]:  # Top 5 errors
                findings['root_causes'].append({
                    'type': 'event_error',
                    'description': f'Error event: {error["reason"]}',
                    'message': error['message'],
                    'count': error['count'],
                    'severity': 'high',
                    'file': file_path
                })
        
        if warning_events:
            for warning in warning_events[:5]:  # Top 5 warnings
                findings['contributing_factors'].append({
                    'type': 'event_warning',
                    'description': f'Warning event: {warning["reason"]}',
                    'message': warning['message'],
                    'count': warning['count'],
                    'severity': 'medium',
                    'file': file_path
                })
        
        return findings
    
    def _analyze_config_resource(self, resource_data: Dict, file_path: str, kind: str) -> Dict:
        """Analyze ConfigMap, Secret, or Service YAML"""
        findings = {
            'root_causes': [],
            'contributing_factors': [],
            'evidence': [],
            'recommendations': []
        }
        
        # Check if resource exists
        if not resource_data:
            findings['contributing_factors'].append({
                'type': 'missing_config',
                'description': f'{kind} resource is missing or empty',
                'severity': 'medium',
                'file': file_path
            })
        
        return findings
    
    def _analyze_generic(self, data: Dict, file_path: str) -> Dict:
        """Generic analysis for unknown YAML types"""
        findings = {
            'root_causes': [],
            'contributing_factors': [],
            'evidence': [],
            'recommendations': []
        }
        
        # Look for common error indicators
        if isinstance(data, dict):
            # Check for status fields
            if 'status' in data:
                status = data['status']
                if isinstance(status, dict):
                    # Look for error conditions
                    for key, value in status.items():
                        if 'error' in key.lower() or 'fail' in key.lower():
                            findings['evidence'].append({
                                'type': 'status_indicator',
                                'key': key,
                                'value': str(value),
                                'file': file_path
                            })
        
        return findings
    
    def _prioritize_findings(self, analysis: Dict) -> Dict:
        """Deduplicate and prioritize findings"""
        # Deduplicate root causes
        seen_rc = {}
        unique_rc = []
        for rc in analysis['root_causes']:
            key = f"{rc.get('type')}_{rc.get('description', '')}"
            if key not in seen_rc:
                seen_rc[key] = True
                unique_rc.append(rc)
        
        analysis['root_causes'] = unique_rc
        
        # Sort by severity
        severity_order = {'high': 0, 'medium': 1, 'low': 2}
        analysis['root_causes'].sort(key=lambda x: severity_order.get(x.get('severity', 'low'), 2))
        analysis['contributing_factors'].sort(key=lambda x: severity_order.get(x.get('severity', 'low'), 2))
        
        return analysis
    
    def _generate_summary(self, analysis: Dict) -> str:
        """Generate human-readable summary"""
        summary_parts = []
        
        if analysis['root_causes']:
            summary_parts.append(f"Identified {len(analysis['root_causes'])} root cause(s):")
            for i, rc in enumerate(analysis['root_causes'][:3], 1):  # Top 3
                summary_parts.append(f"  {i}. {rc.get('description', 'Unknown')}")
        
        if analysis['contributing_factors']:
            summary_parts.append(f"\nFound {len(analysis['contributing_factors'])} contributing factor(s)")
        
        if analysis['recommendations']:
            summary_parts.append(f"\nGenerated {len(analysis['recommendations'])} recommendation(s)")
        
        return '\n'.join(summary_parts) if summary_parts else "No significant findings identified."


def main():
    """Example usage"""
    analyzer = RootCauseAnalyzerYAML()
    
    # Example data analyzer results
    example_data = {
        'data': {
            '/path/to/pod.yaml': {
                'file_type': 'yaml',
                'raw_data': {'kind': 'Pod', 'status': {'phase': 'Failed'}},
                'metadata': {'kind': 'Pod'}
            }
        }
    }
    
    result = analyzer.analyze(example_data)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
