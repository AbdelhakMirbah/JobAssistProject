import { getFirestoreDB } from './firebase_client.js';

async function main() {
  console.log('🔄 Checking Firebase connection...');
  try {
    const db = getFirestoreDB();
    const testDoc = db.collection('system_health').doc('ping');
    await testDoc.set({
      timestamp: new Date().toISOString(),
      status: 'operational',
      client: 'Mac local jobAssistant'
    });
    const snapshot = await testDoc.get();
    console.log('✅ Firebase connection SUCCESSFUL!');
    console.log('📄 Test Document read back:', snapshot.data());
  } catch (error) {
    console.error('❌ Firebase connection error:', error.message);
    process.exit(1);
  }
}

main();
