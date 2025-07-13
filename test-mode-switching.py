#!/usr/bin/env python3
"""
Test script to validate the event-driven mode configuration for the scraper infrastructure
"""
import json
import boto3
import time
from datetime import datetime

def test_lambda_invocation(mode, session_id, test_name):
    """Test invoking the Lambda function with different modes"""
    print(f"\n🧪 {test_name}")
    print("=" * 50)
    
    lambda_client = boto3.client('lambda')
    
    # Prepare test payload
    payload = {
        "mode": mode,
        "session_id": session_id
    }
    
    if mode == "testing":
        payload["single_area"] = "chofu-city"
    elif mode == "normal":
        payload["single_area"] = "shibuya-city"
    elif mode == "stealth":
        payload["max_properties"] = 10000
        payload["entry_point"] = "list_page_1"
    
    print(f"📤 Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = lambda_client.invoke(
            FunctionName='trigger-scraper',
            InvocationType='RequestResponse',
            Payload=json.dumps(payload)
        )
        
        # Parse response
        response_payload = json.loads(response['Payload'].read())
        print(f"📥 Response Status: {response['StatusCode']}")
        print(f"📥 Response: {json.dumps(response_payload, indent=2)}")
        
        return response['StatusCode'] == 200
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

def test_eventbridge_rules():
    """Test EventBridge rules status"""
    print(f"\n🎯 EventBridge Rules Status")
    print("=" * 50)
    
    events_client = boto3.client('events')
    
    # Test rule names
    rule_names = [
        'testing-session-rule',
        'normal-session-rule', 
        'stealth-scraper-morning-1',
        'stealth-scraper-morning-2',
        'stealth-scraper-afternoon-1',
        'stealth-scraper-afternoon-2',
        'stealth-scraper-evening-1',
        'stealth-scraper-evening-2',
        'stealth-scraper-night-1',
        'stealth-scraper-night-2'
    ]
    
    rule_status = {}
    
    for rule_name in rule_names:
        try:
            response = events_client.describe_rule(Name=rule_name)
            rule_status[rule_name] = response['State']
            state_emoji = "✅" if response['State'] == 'ENABLED' else "⭕"
            print(f"{state_emoji} {rule_name}: {response['State']}")
        except Exception as e:
            print(f"❌ {rule_name}: ERROR - {str(e)}")
            rule_status[rule_name] = "ERROR"
    
    return rule_status

def test_mode_switching():
    """Test enabling/disabling different modes"""
    print(f"\n🔄 Mode Switching Test")
    print("=" * 50)
    
    events_client = boto3.client('events')
    
    try:
        # Test 1: Enable testing mode (disable stealth)
        print("🧪 Enabling Testing Mode...")
        events_client.enable_rule(Name='testing-session-rule')
        
        # Disable some stealth rules
        stealth_rules = ['stealth-scraper-morning-1', 'stealth-scraper-morning-2']
        for rule in stealth_rules:
            events_client.disable_rule(Name=rule)
            print(f"⭕ Disabled {rule}")
        
        print("✅ Testing mode enabled")
        
        time.sleep(2)
        
        # Test 2: Re-enable stealth mode (disable testing)
        print("\n🥷 Re-enabling Stealth Mode...")
        events_client.disable_rule(Name='testing-session-rule')
        
        for rule in stealth_rules:
            events_client.enable_rule(Name=rule)
            print(f"✅ Enabled {rule}")
        
        print("✅ Stealth mode restored")
        
        return True
        
    except Exception as e:
        print(f"❌ Mode switching error: {str(e)}")
        return False

def main():
    """Main test function"""
    print("🚀 Scraper Infrastructure Mode Configuration Test")
    print("=" * 60)
    print(f"⏰ Test Time: {datetime.now().isoformat()}")
    
    # Test 1: EventBridge Rules Status
    rule_status = test_eventbridge_rules()
    
    # Test 2: Lambda Function Invocations
    test_results = {}
    test_results['testing'] = test_lambda_invocation(
        "testing", 
        "test-session-manual", 
        "Testing Mode Lambda Invocation"
    )
    
    test_results['normal'] = test_lambda_invocation(
        "normal", 
        "normal-session-manual", 
        "Normal Mode Lambda Invocation" 
    )
    
    test_results['stealth'] = test_lambda_invocation(
        "stealth", 
        "stealth-session-manual", 
        "Stealth Mode Lambda Invocation"
    )
    
    # Test 3: Mode Switching
    mode_switching_success = test_mode_switching()
    
    # Summary
    print(f"\n📊 Test Summary")
    print("=" * 50)
    
    # EventBridge Rules
    enabled_rules = sum(1 for status in rule_status.values() if status == 'ENABLED')
    print(f"🎯 EventBridge Rules: {enabled_rules}/{len(rule_status)} enabled")
    
    # Lambda Tests
    successful_tests = sum(1 for success in test_results.values() if success)
    print(f"🧪 Lambda Tests: {successful_tests}/{len(test_results)} successful")
    
    # Mode Switching
    print(f"🔄 Mode Switching: {'✅ Success' if mode_switching_success else '❌ Failed'}")
    
    # Overall
    overall_success = (
        successful_tests == len(test_results) and 
        mode_switching_success and
        enabled_rules > 0
    )
    
    print(f"\n🎯 Overall Result: {'🎉 ALL TESTS PASSED' if overall_success else '⚠️  SOME TESTS FAILED'}")
    
    if overall_success:
        print("\n✅ The consolidated scraper infrastructure is working correctly!")
        print("✅ Event-driven mode configuration is functional!")
        print("✅ Mode switching via EventBridge rules works!")
    else:
        print("\n⚠️  Please check the failed tests and fix any issues.")

if __name__ == "__main__":
    main()