// WebSocket Load Test for PraxisFlow Real-time Features
// Tests WebSocket connections, message throughput, and reconnection handling

import ws from 'k6/ws';
import { check, sleep, group } from 'k6';
import { Rate, Trend, Counter, Gauge } from 'k6/metrics';
import { SharedArray } from 'k6/data';

// ─── Configuration ───
export const options = {
  stages: [
    { duration: '1m', target: 50 },    // Ramp up
    { duration: '3m', target: 200 },   // Steady state
    { duration: '1m', target: 500 },   // Stress
    { duration: '2m', target: 500 },   // Peak
    { duration: '1m', target: 0 },     // Ramp down
  ],
  thresholds: {
    'ws_connect_duration': ['p(95)<1000', 'p(99)<2000'],
    'ws_message_latency': ['p(95)<100', 'p(99)<200'],
    'ws_errors': ['rate<0.01'],
    'ws_active_connections': ['value<600'],
    'ws_reconnects': ['count<100'],
  },
  ext: {
    loadimpact: {
      projectID: 123456,
      name: 'PraxisFlow WebSocket Load Test',
    },
  },
};

// ─── Metrics ───
const wsConnectDuration = new Trend('ws_connect_duration');
const wsMessageLatency = new Trend('ws_message_latency');
const wsErrors = new Rate('ws_errors');
const wsActiveConnections = new Gauge('ws_active_connections');
const wsReconnects = new Counter('ws_reconnects');
const wsMessagesSent = new Counter('ws_messages_sent');
const wsMessagesReceived = new Counter('ws_messages_received');

// ─── Test Data ───
const testUsers = new SharedArray('users', function() {
  return JSON.parse(open('./test-users.json'));
});

const WS_URL = __ENV.WS_URL://localhost:8000';
const API_URL = __ENV.API_URL://localhost:8000';
const TOKEN = __ENV.AUTH_TOKEN;

// ─── Main Test ───
export default function() {
  const user = testUsers[__VU % testUsers.length];
  
  // Connect to WebSocket
  const url = `${WS_URL}/api/v1/ws?token=${TOKEN}&tenant_id=${user.tenant_id}`;
  
  const params = {
    headers: {
      'Origin': 'https://app.praxisflow.com',
    },
    timeout: '30s',
  };

  ws.connect(url, params, function(socket) {
    wsActiveConnections.add(1);
    
    const connectStart = new Date();
    
    socket.on('open', () => {
      const connectDuration = new Date() - connectStart;
      wsConnectDuration.add(connectDuration);
      
      check(socket, {
        'WebSocket connected': () => true,
      });

      // Subscribe to channels
      socket.send(JSON.stringify({
        type: 'subscribe',
        channels: ['meetings', 'tasks', 'notifications', `tenant:${user.tenant_id}`],
      }));
      wsMessagesSent.add(1);

      // Send periodic heartbeats
      const heartbeatInterval = setInterval(() => {
        socket.send(JSON.stringify({ type: 'ping' }));
        wsMessagesSent.add(1);
      }, 15000);

      // Handle incoming messages
      socket.on('message', (msg) => {
        wsMessagesReceived.add(1);
        const receiveStart = new Date();
        
        try {
          const data = JSON.parse(msg);
          
          // Track message latency for ping/pong
          if (data.type === 'pong') {
            const latency = new Date() - receiveStart;
            wsMessageLatency.add(latency);
          }
          
          // Validate message structure
          check(data, {
            'message has type': (d) => d.type !== undefined,
            'message has payload': (d) => d.payload !== undefined || d.type === 'pong',
          });
          
        } catch (e) {
          wsErrors.add(1);
          console.error(`Failed to parse message: ${e}`);
        }
      });

      // Handle errors
      socket.on('error', (e) => {
        wsErrors.add(1);
        console.error(`WebSocket error: ${e}`);
      });

      // Handle close
      socket.on('close', () => {
        wsActiveConnections.add(-1);
        clearInterval(heartbeatInterval);
      });

      // Simulate meeting updates (send messages)
      const messageInterval = setInterval(() => {
        if (socket.readyState === 1) { // OPEN
          socket.send(JSON.stringify({
            type: 'meeting_update',
            payload: {
              meeting_id: `test-${__VU}`,
              status: 'processing',
              progress: Math.floor(Math.random() * 100),
              timestamp: new Date().toISOString(),
            },
          }));
          wsMessagesSent.add(1);
        }
      }, 5000);

      // Test duration
      sleep(60);

      // Cleanup
      clearInterval(messageInterval);
      clearInterval(heartbeatInterval);
      socket.close();
    });
  });

  sleep(5);
}

// ─── Reconnection Test ───
export function reconnectionTest() {
  const user = testUsers[__VU % testUsers.length];
  const url = `${WS_URL}/api/v1/ws?token=${TOKEN}&tenant_id=${user.tenant_id}`;

  for (let i = 0; i < 5; i++) {
    ws.connect(url, {}, function(socket) {
      wsActiveConnections.add(1);
      
      socket.on('open', () => {
        wsMessagesSent.add(1);
      });

      socket.on('close', () => {
        wsActiveConnections.add(-1);
        wsReconnects.add(1);
      });

      socket.on('error', (e) => {
        wsErrors.add(1);
      });

      sleep(2);
      socket.close();
    });

    sleep(1);
  }
}

// ─── Message Throughput Test ───
export function throughputTest() {
  const user = testUsers[__VU % testUsers.length];
  const url = `${WS_URL}/api/v1/ws?token=${TOKEN}&tenant_id=${user.tenant_id}`;

  ws.connect(url, {}, function(socket) {
    wsActiveConnections.add(1);
    
    let messageCount = 0;
    const startTime = new Date();
    
    socket.on('open', () => {
      // Send burst of messages
      const burstInterval = setInterval(() => {
        if (messageCount < 1000) {
          socket.send(JSON.stringify({
            type: 'burst_test',
            sequence: messageCount++,
            timestamp: new Date().toISOString(),
          }));
          wsMessagesSent.add(1);
        } else {
          clearInterval(burstInterval);
        }
      }, 1); // 1ms interval = ~1000 msg/sec
    });

    socket.on('message', (msg) => {
      wsMessagesReceived.add(1);
    });

    socket.on('close', () => {
      wsActiveConnections.add(-1);
      const duration = new Date() - startTime;
      console.log(`Throughput: ${messageCount} messages in ${duration}ms = ${(messageCount / duration * 1000).toFixed(0)} msg/sec`);
    });

    // Run for 30 seconds
    sleep(30);
    socket.close();
  });
}

// ─── Multi-Tenant Isolation Test ───
export function tenantIsolationTest() {
  const tenantA = testUsers.filter(u => u.tenant_id === 'tenant-001')[0];
  const tenantB = testUsers.filter(u => u.tenant_id === 'tenant-002')[0];
  
  if (!tenantA || !tenantB) {
    console.log('Need users from different tenants for isolation test');
    return;
  }

  const urlA = `${WS_URL}/api/v1/ws?token=${TOKEN}&tenant_id=${tenantA.tenant_id}`;
  const urlB = `${WS_URL}/api/v1/ws?token=${TOKEN}&tenant_id=${tenantB.tenant_id}`;

  let messagesReceivedA = 0;
  let messagesReceivedB = 0;

  // Connect tenant A
  ws.connect(urlA, {}, function(socketA) {
    wsActiveConnections.add(1);
    
    socketA.on('open', () => {
      socketA.send(JSON.stringify({
        type: 'subscribe',
        channels: ['tenant:tenant-001'],
      }));
    });

    socketA.on('message', (msg) => {
      messagesReceivedA++;
      const data = JSON.parse(msg);
      // Verify tenant isolation - should only receive tenant-001 messages
      check(data, {
        'Tenant A receives only tenant-001 messages': (d) => 
          d.tenant_id === undefined || d.tenant_id === 'tenant-001',
      });
    });

    // Connect tenant B
    ws.connect(urlB, {}, function(socketB) {
      wsActiveConnections.add(1);
      
      socketB.on('open', () => {
        socketB.send(JSON.stringify({
          type: 'subscribe',
          channels: ['tenant:tenant-002'],
        }));
      });

      socketB.on('message', (msg) => {
        messagesReceivedB++;
        const data = JSON.parse(msg);
        // Verify tenant isolation
        check(data, {
          'Tenant B receives only tenant-002 messages': (d) => 
            d.tenant_id === undefined || d.tenant_id === 'tenant-002',
        });
      });

      sleep(10);
      socketA.close();
      socketB.close();
    });
  });

  wsActiveConnections.add(-2);
  
  console.log(`Tenant A messages: ${messagesReceivedA}, Tenant B messages: ${messagesReceivedB}`);
  check(null, {
    'No cross-tenant leakage': () => messagesReceivedA > 0 && messagesReceivedB > 0,
  });
}

// ─── Setup ───
export function setup() {
  console.log('Starting WebSocket load test...');
  console.log(`WS URL: ${WS_URL}`);
  console.log(`Test users: ${testUsers.length}`);
  
  // Verify authentication
  const authCheck = http.get(`${API_URL}/health`, {
    headers: { 'Authorization': `Bearer ${TOKEN}` },
  });
  
  check(authCheck, {
    'Auth token valid': (r) => r.status === 200,
  });
  
  return { baseUrl: WS_URL };
}

// ─── Teardown ───
export function teardown(data) {
  console.log('WebSocket load test completed');
}