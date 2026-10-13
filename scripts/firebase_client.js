import admin from 'firebase-admin';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

dotenv.config();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const serviceAccountPath = process.env.FIREBASE_SERVICE_ACCOUNT_PATH || 
  path.resolve(__dirname, '../credentials/serviceAccountKey.json');

let db = null;

export function getFirestoreDB() {
  if (db) return db;

  if (fs.existsSync(serviceAccountPath)) {
    const serviceAccount = JSON.parse(fs.readFileSync(serviceAccountPath, 'utf8'));
    if (!admin.apps.length) {
      admin.initializeApp({
        credential: admin.credential.cert(serviceAccount),
        projectId: process.env.FIREBASE_PROJECT_ID || serviceAccount.project_id
      });
    }
    db = admin.firestore();
    return db;
  } else {
    throw new Error(
      `Firebase serviceAccountKey.json not found at: ${serviceAccountPath}.\n` +
      `Please download it from Firebase Console -> Project Settings -> Service Accounts -> Generate new private key.`
    );
  }
}

export default { getFirestoreDB };
