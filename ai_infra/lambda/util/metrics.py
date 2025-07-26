"""
Metrics emission utilities for Lean v1.3 pipeline.

This module provides centralized metric emission for tracking
pipeline performance and key metrics across all components.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

import boto3
from botocore.exceptions import ClientError

# Import centralized config helper
try:
    from .config import get_config
except ImportError:
    try:
        from config import get_config
    except ImportError:
        logger = logging.getLogger(__name__)
        logger.warning("Centralized config not available, falling back to direct os.getenv access")
        get_config = None

logger = logging.getLogger(__name__)


class MetricsEmitter:
    """Centralized metrics emission for the Lean v1.3 pipeline."""
    
    def __init__(self, namespace: str = "TokyoRealEstate/Lean"):
        """
        Initialize metrics emitter.
        
        Args:
            namespace: CloudWatch namespace for metrics
        """
        self.namespace = namespace
        self.cloudwatch = None
        self.metrics_buffer = []
        
        # Initialize CloudWatch client only if available
        try:
            if get_config:
                aws_region = get_config().get_str('AWS_REGION', 'ap-northeast-1')
            else:
                aws_region = os.getenv('AWS_REGION', 'ap-northeast-1')
            self.cloudwatch = boto3.client('cloudwatch', region_name=aws_region)
        except Exception as e:
            logger.warning(f"CloudWatch client not available: {e}")
    
    def emit_metric(self, metric_name: str, value: Union[int, float], 
                   unit: str = "Count", dimensions: Optional[Dict[str, str]] = None) -> None:
        """
        Emit a single metric to CloudWatch.
        
        Args:
            metric_name: Name of the metric
            value: Metric value
            unit: CloudWatch unit (Count, Seconds, Percent, etc.)
            dimensions: Optional metric dimensions
        """
        if not self.cloudwatch:
            logger.debug(f"Metric {metric_name}={value} (CloudWatch unavailable)")
            return
            
        try:
            # Prepare metric data
            metric_data = {
                'MetricName': metric_name,
                'Value': value,
                'Unit': unit,
                'Timestamp': datetime.now(timezone.utc)
            }
            
            # Add dimensions if provided
            if dimensions:
                metric_data['Dimensions'] = [
                    {'Name': k, 'Value': str(v)} for k, v in dimensions.items()
                ]
            
            # Send to CloudWatch
            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=[metric_data]
            )
            
            logger.debug(f"Emitted metric: {metric_name}={value}")
            
        except Exception as e:
            logger.error(f"Failed to emit metric {metric_name}: {e}")
    
    def emit_batch_metrics(self, metrics: Dict[str, Union[int, float]], 
                          unit: str = "Count", 
                          dimensions: Optional[Dict[str, str]] = None) -> None:
        """
        Emit multiple metrics in a batch.
        
        Args:
            metrics: Dictionary of metric_name -> value
            unit: CloudWatch unit for all metrics
            dimensions: Optional dimensions for all metrics
        """
        if not self.cloudwatch:
            logger.debug(f"Batch metrics: {metrics} (CloudWatch unavailable)")
            return
            
        try:
            # Prepare batch metric data
            metric_data = []
            timestamp = datetime.now(timezone.utc)
            
            for metric_name, value in metrics.items():
                data = {
                    'MetricName': metric_name,
                    'Value': value,
                    'Unit': unit,
                    'Timestamp': timestamp
                }
                
                if dimensions:
                    data['Dimensions'] = [
                        {'Name': k, 'Value': str(v)} for k, v in dimensions.items()
                    ]
                
                metric_data.append(data)
            
            # Send batch to CloudWatch (max 20 metrics per call)
            for i in range(0, len(metric_data), 20):
                batch = metric_data[i:i+20]
                self.cloudwatch.put_metric_data(
                    Namespace=self.namespace,
                    MetricData=batch
                )
            
            logger.debug(f"Emitted {len(metrics)} metrics in batch")
            
        except Exception as e:
            logger.error(f"Failed to emit batch metrics: {e}")
    
    def emit_pipeline_metrics(self, stage: str, metrics: Dict[str, Any]) -> None:
        """
        Emit pipeline-specific metrics with stage dimensions.
        
        Args:
            stage: Pipeline stage (ETL, PromptBuilder, LLM, etc.)
            metrics: Dictionary of metrics to emit
        """
        dimensions = {'Stage': stage}
        
        # Extract numeric metrics
        numeric_metrics = {}
        for key, value in metrics.items():
            if isinstance(value, (int, float)) and not key.endswith('_at'):
                numeric_metrics[key] = value
        
        if numeric_metrics:
            self.emit_batch_metrics(numeric_metrics, dimensions=dimensions)
    
    def emit_error_metric(self, error_type: str, stage: str = "Unknown") -> None:
        """
        Emit an error metric.
        
        Args:
            error_type: Type of error (ValidationError, S3Error, etc.)
            stage: Pipeline stage where error occurred
        """
        self.emit_metric(
            'Errors',
            1,
            dimensions={'ErrorType': error_type, 'Stage': stage}
        )
    
    def emit_execution_time(self, stage: str, seconds: float) -> None:
        """
        Emit execution time metric.
        
        Args:
            stage: Pipeline stage
            seconds: Execution time in seconds
        """
        self.emit_metric(
            'ExecutionTime',
            seconds,
            unit='Seconds',
            dimensions={'Stage': stage}
        )


# Global metrics emitter instance
_metrics_emitter = None


def get_metrics_emitter() -> MetricsEmitter:
    """Get the global metrics emitter instance."""
    global _metrics_emitter
    if _metrics_emitter is None:
        _metrics_emitter = MetricsEmitter()
    return _metrics_emitter


# Convenience functions for common metrics
def emit_metric(metric_name: str, value: Union[int, float], 
               unit: str = "Count", dimensions: Optional[Dict[str, str]] = None) -> None:
    """Emit a single metric."""
    get_metrics_emitter().emit_metric(metric_name, value, unit, dimensions)


def emit_batch_metrics(metrics: Dict[str, Union[int, float]], 
                      unit: str = "Count",
                      dimensions: Optional[Dict[str, str]] = None) -> None:
    """Emit multiple metrics in a batch."""
    get_metrics_emitter().emit_batch_metrics(metrics, unit, dimensions)


def emit_pipeline_metrics(stage: str, metrics: Dict[str, Any]) -> None:
    """Emit pipeline stage metrics."""
    get_metrics_emitter().emit_pipeline_metrics(stage, metrics)


def emit_error_metric(error_type: str, stage: str = "Unknown") -> None:
    """Emit an error metric."""
    get_metrics_emitter().emit_error_metric(error_type, stage)


def emit_execution_time(stage: str, seconds: float) -> None:
    """Emit execution time metric."""
    get_metrics_emitter().emit_execution_time(stage, seconds)


# Standard pipeline metrics functions
def emit_properties_processed(count: int, stage: str = "ETL") -> None:
    """Emit PropertiesProcessed metric."""
    emit_metric('PropertiesProcessed', count, dimensions={'Stage': stage})


def emit_candidates_enqueued(count: int) -> None:
    """Emit CandidatesEnqueued metric."""
    emit_metric('CandidatesEnqueued', count)


def emit_candidates_suppressed(count: int) -> None:
    """Emit CandidatesSuppressed metric."""
    emit_metric('CandidatesSuppressed', count)


def emit_llm_calls(count: int) -> None:
    """Emit LLM.Calls metric."""
    emit_metric('LLM.Calls', count)


def emit_llm_schema_failures(count: int) -> None:
    """Emit Evaluator.SchemaFail metric."""
    emit_metric('Evaluator.SchemaFail', count)


def emit_digest_sent(count: int = 1) -> None:
    """Emit Digest.Sent metric."""
    emit_metric('Digest.Sent', count)


# Context manager for timing execution
class MetricsTimer:
    """Context manager for timing execution and emitting metrics."""
    
    def __init__(self, stage: str):
        self.stage = stage
        self.start_time = None
    
    def __enter__(self):
        self.start_time = datetime.now(timezone.utc)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration = (datetime.now(timezone.utc) - self.start_time).total_seconds()
            emit_execution_time(self.stage, duration)
            
            if exc_type:
                # Also emit error metric if exception occurred
                error_type = exc_type.__name__ if exc_type else 'UnknownError'
                emit_error_metric(error_type, self.stage)


# Usage examples and testing
if __name__ == "__main__":
    # Example usage
    emitter = get_metrics_emitter()
    
    # Single metric
    emit_metric('TestMetric', 42)
    
    # Batch metrics
    emit_batch_metrics({
        'PropertiesProcessed': 150,
        'CandidatesEnqueued': 12,
        'CandidatesSuppressed': 138
    })
    
    # Pipeline metrics with timing
    with MetricsTimer('TestStage'):
        import time
        time.sleep(0.1)  # Simulate work
    
    print("Metrics emission test completed")