# LLM Processing Lambda Function

This Lambda function processes real estate listings using OpenAI's API for investment analysis.

## Recent Changes (July 2025)

### Switched from Batch API to Synchronous API
- **Previous**: Used OpenAI Batch API with 24-hour processing window
- **Current**: Uses synchronous chat completions API for immediate results
- **Model**: Updated to use `o3` model (cheaper and more advanced than GPT-4o)

### Key Features
- Processes ~100 real estate listings per day
- Includes 20 property images per listing for visual analysis
- Integrates with DynamoDB for market context
- Maintains exact same input/output format for compatibility
- Robust retry logic with exponential backoff

### Configuration
- **Model Selection**: Set `OPENAI_MODEL` environment variable
  - `o3` (default): Best quality analysis (~$200/month)
  - `o3-mini`: Cost-optimized option (~$35/month)

### Performance
- Sequential processing with 500ms delay between requests
- Handles rate limits gracefully
- 60-minute Lambda timeout for processing 100+ listings

### Cost Comparison
| Model | Monthly Cost | Notes |
|-------|--------------|-------|
| o3 | ~$200 | Best quality, includes vision |
| o3-mini | ~$35 | 82% cost savings, good for basic analysis |
| GPT-4o (old) | ~$250 | More expensive, less capable |

### Testing
```bash
# Set environment variables
export OUTPUT_BUCKET=tokyo-real-estate-ai-data
export OPENAI_MODEL=o3

# Run local test
python app.py
```