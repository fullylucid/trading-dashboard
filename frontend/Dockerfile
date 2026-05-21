# Build stage
FROM node:18-alpine as build

WORKDIR /app

# Copy package files
COPY package.json package-lock.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY public ./public
COPY src ./src

# Build application
RUN npm run build

# Production stage
FROM node:18-alpine

WORKDIR /app

# Install serve to run the production build
RUN npm install -g serve

# Copy built application from build stage
COPY --from=build /app/build ./build

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:5000 || exit 1

# Run application
CMD ["serve", "-s", "build", "-l", "5000"]
