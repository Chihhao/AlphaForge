FROM node:18-alpine

WORKDIR /app

# Copy package.json and package-lock.json (if available)
COPY package.json package-lock.json* ./

# Install dependencies
RUN npm install

# Copy all files
COPY . .

# Build the Next.js application
# Ignore ESLint and TypeScript errors during build if any exist to ensure successful build on NAS
ENV NEXT_TELEMETRY_DISABLED 1
RUN npm run build

EXPOSE 3000

# Start the application
CMD ["npm", "start"]
