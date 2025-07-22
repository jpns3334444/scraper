# Lean v1.3 Migration Notes

## Executive Summary

Lean v1.3 transforms the Tokyo Real Estate Analysis system from an **LLM-heavy** to a **deterministic-first** architecture, achieving:

- **~80% LLM cost reduction** by gating candidates
- **10x faster processing** with Python-based scoring
- **Deterministic results** for consistent investment decisions
- **Improved reliability** with schema-enforced outputs

## Migration Changes Overview

### Before (Legacy Mode)
- ❌ Every property sent to LLM (~500+ properties/day)
- ❌ Subjective scoring variations
- ❌ Per-property email reports (spam risk)
- ❌ 2000+ tokens per property
- ❌ Hours of processing time
- ❌ Inconsistent comparable selection

### After (Lean v1.3)
- ✅ Only gated candidates sent to LLM (~100 properties/day)
- ✅ Deterministic scoring with clear rules
- ✅ Single daily digest email
- ✅ ~1200 tokens per candidate
- ✅ Minutes of processing time
- ✅ Algorithm-selected ≤8 comparables

## Technical Implementation

### 1. Deterministic Scoring Engine

**File**: `analysis/lean_scoring.py`

```python
# Base Components (60 points)
BASE_WEIGHTS = {
    'ward_discount': 0.417,      # 25 points
    'building_discount': 0.167,  # 10 points  
    'comps_consistency': 0.167,  # 10 points
    'condition': 0.117,         # 7 points
    'size_efficiency': 0.067,   # 4 points
    'carry_cost': 0.067         # 4 points
}

# Gating Rules
BUY_CANDIDATE: final_score ≥ 75 AND ward_discount ≤ -12% AND dq_penalty ≥ -4
WATCH: final_score 60-74 OR ward_discount -8% to -11.99%
REJECT: everything else
```

### 2. Comparable Selection Algorithm

**File**: `analysis/comparables.py`

```python
# Filtering Criteria
- Price per sqm: ±30% of target
- Size: ±25% of target
- Age: ±10 years of target
- Maximum: 8 comparables
- Sorting: price delta, then size delta
```

### 3. Lean Prompt Structure

**File**: `ai-infra/lambda/prompt_builder/app.py`

```python
# Restrictions
- Only candidates processed
- ≤8 comparables included
- ≤3 images per property
- Target ~1200 tokens
```

### 4. Minimal LLM Schema

**File**: `schemas/evaluation_min.json`

```json
{
  "required": ["upsides", "risks", "justification"],
  "properties": {
    "upsides": {"maxItems": 3, "minLength": 10, "maxLength": 200},
    "risks": {"maxItems": 3, "minLength": 10, "maxLength": 200},
    "justification": {"minLength": 50, "maxLength": 300}
  }
}
```

### 5. Daily Digest System

**File**: `notifications/daily_digest.py`

- **HTML**: Market summary + candidate table + ward analysis
- **CSV**: Candidate export for further analysis
- **Single Email**: Replaces per-property emails

## Data Flow Changes

### Legacy Pipeline
```
Raw Data → LLM Analysis → Individual Reports → Email Spam
```

### Lean v1.3 Pipeline
```
Raw Data → Deterministic Scoring → Candidate Gating → Lean LLM → Daily Digest
```

## Performance Metrics

### Expected Improvements

| Metric | Legacy | Lean v1.3 | Improvement |
|---------|---------|-----------|-------------|
| **LLM API Calls** | ~500/day | ~100/day | 80% reduction |
| **Processing Time** | 4-6 hours | 20-30 minutes | 10x faster |
| **Token Usage** | 1M+ tokens/day | 200K tokens/day | 80% reduction |
| **Email Volume** | 500+ emails/day | 1 email/day | 99.8% reduction |
| **Candidate Precision** | Subjective | Deterministic | Consistent |

### Key Metrics to Monitor

```bash
# Critical Success Metrics
PropertiesProcessed: 300-800/day     # Total analyzed
CandidatesEnqueued: 60-150/day       # Meeting gating criteria (~20%)
CandidatesSuppressed: 150-650/day    # Rejected by gating (~80%)
LLM.Calls: 60-150/day               # Actual API usage
Evaluator.SchemaFail: <5/day        # Failed validations
Digest.Sent: 1/day                  # Email delivery
```

## Feature Flags Configuration

### Environment Variables

```bash
# Enable Lean Mode (Master Switch)
LEAN_MODE=1                    # 0=Legacy, 1=Lean (default: 0)

# Feature Components
LEAN_SCORING=1                 # Deterministic scoring (default: 1)
LEAN_PROMPT=1                  # Lean prompt format (default: 1)  
LEAN_SCHEMA_ENFORCE=1          # Strict schema validation (default: 1)

# Limits
MAX_CANDIDATES_PER_DAY=120     # Candidate processing limit
```

### Rollback Safety

If issues arise, immediately rollback:

```bash
# Emergency Rollback
export LEAN_MODE=0
./ai-infra/deploy-ai.sh

# Verify rollback
aws lambda get-function-configuration \
  --function-name ai-stack-etl \
  --query 'Environment.Variables.LEAN_MODE'
```

## Testing Coverage

### New Test Suites

1. **`tests/test_scoring_basic.py`**
   - Ward discount linearity
   - DQ penalty calculations  
   - Gating rule accuracy
   - Edge case handling

2. **`tests/test_comparables_basic.py`**
   - Filtering criteria (±30%, ±25%, ±10y)
   - Sorting algorithms
   - ≤8 limit enforcement
   - Market statistics

3. **`tests/test_prompt_lean.py`**
   - Structure validation
   - Token count estimation
   - Image prioritization
   - Candidate-only processing

4. **`tests/test_eval_schema.py`**
   - JSON schema validation
   - Field length constraints
   - Required field checks
   - Error handling

5. **`tests/test_digest.py`**
   - HTML structure validation
   - CSV format accuracy
   - Market summary content
   - Multi-language support

### Running Tests

```bash
# Complete test suite
pytest tests/ -v

# Quick validation
pytest tests/test_scoring_basic.py::TestLeanScoringBasics::test_gating_rules_buy_candidate -v
```

## Deployment Strategy

### Phase 1: Parallel Deployment
- Deploy Lean v1.3 with `LEAN_MODE=0` (disabled)
- Validate infrastructure and dependencies
- Run parallel testing for 1-2 days

### Phase 2: Gradual Rollout
- Enable `LEAN_MODE=1` during low-traffic hours
- Monitor key metrics for anomalies
- Collect performance data

### Phase 3: Full Migration  
- Switch to Lean mode permanently
- Remove legacy code paths
- Optimize based on production metrics

## Risk Mitigation

### High-Risk Areas

1. **Gating Too Aggressive**
   - **Risk**: Missing good candidates
   - **Mitigation**: Monitor candidate ratios, adjust thresholds
   - **Alert**: `CandidatesEnqueued < 50/day`

2. **Schema Validation Failures**
   - **Risk**: LLM outputs not parsing
   - **Mitigation**: Robust retry logic, fallback handling
   - **Alert**: `Evaluator.SchemaFail > 10/day`

3. **Email Delivery Issues**
   - **Risk**: Daily digest not sent
   - **Mitigation**: SES monitoring, backup notification channels
   - **Alert**: `Digest.Sent != 1/day`

### Monitoring Alerts

```bash
# CloudWatch Alarms
aws cloudwatch put-metric-alarm \
  --alarm-name "LeanMode-LowCandidates" \
  --alarm-description "Too few candidates generated" \
  --metric-name "CandidatesEnqueued" \
  --threshold 30 \
  --comparison-operator LessThanThreshold

aws cloudwatch put-metric-alarm \
  --alarm-name "LeanMode-SchemaFailures" \
  --alarm-description "High schema validation failures" \
  --metric-name "Evaluator.SchemaFail" \
  --threshold 10 \
  --comparison-operator GreaterThanThreshold
```

## Expected Business Impact

### Cost Savings
- **LLM API Costs**: 80% reduction (~$2000/month → ~$400/month)
- **Processing Time**: Staff can review results same day vs next day
- **Email Management**: Elimination of inbox spam, improved signal/noise

### Quality Improvements  
- **Consistency**: Deterministic scoring eliminates subjective variations
- **Transparency**: Clear scoring components for investment decisions
- **Reliability**: Schema validation ensures parseable outputs

### Operational Benefits
- **Faster Iteration**: Minutes vs hours for testing changes
- **Better Monitoring**: Clear metrics for system health
- **Scalability**: System can handle 10x more properties if needed

## Success Criteria Checklist

### Week 1: Infrastructure
- [ ] All Lambda functions deployed successfully
- [ ] Environment variables configured correctly
- [ ] Test suite passing (100% test coverage)
- [ ] Monitoring alerts configured

### Week 2: Functional Validation
- [ ] Candidate gating producing 15-25% selection rate
- [ ] Daily digest emails sending successfully
- [ ] LLM schema validation <5% failure rate
- [ ] Processing time <30 minutes end-to-end

### Month 1: Performance Validation
- [ ] 80% LLM cost reduction achieved
- [ ] No missed high-quality candidates (manual spot checks)
- [ ] User satisfaction maintained or improved
- [ ] System stability >99% uptime

## Post-Migration Tasks

### Immediate (Week 1)
1. Monitor all metrics dashboards daily
2. Conduct user acceptance testing with digest format
3. Fine-tune gating thresholds based on initial results
4. Document any required operational changes

### Short-term (Month 1)
1. Optimize prompt structure for better LLM outputs
2. Enhance digest formatting based on user feedback
3. Implement additional ward-specific analysis
4. Create automated reporting for business metrics

### Long-term (Quarter 1)
1. Machine learning enhancements to scoring algorithm
2. Integration with external market data sources
3. Mobile-friendly digest formats
4. Predictive modeling for market trends

## Rollback Plan

If critical issues emerge:

### Immediate Rollback (5 minutes)
```bash
# Set legacy mode
export LEAN_MODE=0

# Redeploy ETL and prompt builder
cd ai-infra/
./deploy-ai.sh

# Verify legacy mode active
aws lambda invoke --function-name ai-stack-etl test-output.json
grep -i "legacy\|LEAN_MODE.*0" test-output.json
```

### Full System Rollback (30 minutes)
1. Revert all Lambda functions to previous versions
2. Restore legacy environment variables
3. Re-enable per-property email reports
4. Notify stakeholders of rollback
5. Investigate and document root cause

## Conclusion

Lean v1.3 represents a fundamental shift toward deterministic, efficient real estate analysis. The migration reduces costs and complexity while maintaining (and potentially improving) analysis quality through consistent, rule-based scoring.

**Key Success Factors:**
- Gradual rollout with careful monitoring
- Robust testing and rollback procedures  
- Clear metrics for success measurement
- User communication about changes

The system is designed to be **deterministic-first** while preserving AI capabilities where they add the most value—qualitative analysis of pre-qualified candidates.