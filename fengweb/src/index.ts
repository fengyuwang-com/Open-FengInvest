import { createServer } from './server';

const PORT = parseInt(process.env.PORT || '23456', 10);
createServer(PORT);
