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

# Provide the API URL at build time for Next.js static generation
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

RUN npm run build

EXPOSE 3000

# Start the application
CMD ["npm", "start"]
