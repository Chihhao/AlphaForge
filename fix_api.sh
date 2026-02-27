#!/bin/bash
cat << 'API_FILE' > ~/alphaforge-deploy/frontend/lib/api.ts
import axios from 'axios';

// Get the base URL from the browser if we are running in the browser
// This ensures we always hit the same domain (e.g. 10.0.4.3:8000) we are hosted on
// Fall back to NEXT_PUBLIC_API_URL or localhost for SSR and dev
const getBaseUrl = () => {
    if (typeof window !== 'undefined') {
        return window.location.protocol + '//' + window.location.hostname + ':8000';
    }
    return process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
};

const api = axios.create({
    baseURL: getBaseUrl(),
    timeout: 10000,
    headers: {
        'Content-Type': 'application/json',
    },
});

export default api;
API_FILE
