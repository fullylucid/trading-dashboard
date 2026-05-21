#!/bin/bash
# Quick start script for Trading Dashboard

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
setup_backend() {
    echo -e "${BLUE}Setting up backend...${NC}"
    cd "$SCRIPT_DIR/backend"
    
    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi
    
    source venv/bin/activate
    
    # Check if .env exists
    if [ ! -f ".env" ]; then
        echo -e "${YELLOW}Creating .env from template...${NC}"
        cp .env.example .env
        echo -e "${YELLOW}Edit backend/.env and add your FINNHUB_API_KEY${NC}"
    fi
    
    pip install -r requirements.txt
    echo -e "${GREEN}Backend setup complete!${NC}"
}

setup_frontend() {
    echo -e "${BLUE}Setting up frontend...${NC}"
    cd "$SCRIPT_DIR/frontend"
    
    if [ ! -d "node_modules" ]; then
        npm install
    fi
    
    # Check if .env exists
    if [ ! -f ".env" ]; then
        echo -e "${YELLOW}Creating .env from template...${NC}"
        cp .env.example .env
    fi
    
    echo -e "${GREEN}Frontend setup complete!${NC}"
}

run_backend() {
    echo -e "${BLUE}Starting backend...${NC}"
    cd "$SCRIPT_DIR/backend"
    source venv/bin/activate
    python main.py
}

run_frontend() {
    echo -e "${BLUE}Starting frontend...${NC}"
    cd "$SCRIPT_DIR/frontend"
    npm start
}

run_docker() {
    echo -e "${BLUE}Starting Docker containers...${NC}"
    cd "$SCRIPT_DIR"
    
    # Check if .env exists
    if [ ! -f ".env" ]; then
        echo -e "${YELLOW}Creating .env file...${NC}"
        cp backend/.env.example .env
        echo -e "${YELLOW}Edit .env and add your FINNHUB_API_KEY${NC}"
    fi
    
    docker-compose up -d
    
    echo -e "${GREEN}Docker containers started!${NC}"
    echo ""
    echo "Services:"
    echo "  Backend:  http://localhost:8000"
    echo "  Frontend: http://localhost:5000"
    echo "  API Docs: http://localhost:8000/docs"
    echo ""
    echo "View logs: docker-compose logs -f"
}

show_help() {
    cat << EOF
${BLUE}Trading Dashboard - Quick Start${NC}

Usage: $0 [COMMAND]

Commands:
    setup       - Setup both backend and frontend (first time only)
    dev         - Run backend and frontend in development (requires 2 terminals)
    docker      - Run everything in Docker
    docker-logs - View Docker logs
    docker-stop - Stop Docker containers
    help        - Show this help message

Examples:
    $0 setup            # Initial setup
    $0 docker           # Start with Docker (recommended)
    $0 dev              # Terminal 1: Backend, Terminal 2: Frontend

Environment:
    - Backend runs on http://localhost:8000
    - Frontend runs on http://localhost:3000 (dev) or 5000 (docker)
    - API docs at http://localhost:8000/docs

Requirements:
    - Python 3.11+
    - Node.js 18+
    - Docker & Docker Compose (for docker commands)

First time setup:
    1. Get API key from https://finnhub.io
    2. Run: $0 setup
    3. Run: $0 docker

For more info, see README.md

EOF
}

# Main
case "${1:-help}" in
    setup)
        setup_backend
        setup_frontend
        echo ""
        echo -e "${GREEN}✓ Setup complete!${NC}"
        echo "Next step: $0 docker  (or manually run backend/frontend)"
        ;;
    dev)
        setup_backend
        setup_frontend
        echo ""
        echo -e "${YELLOW}Open 2 terminals and run:${NC}"
        echo "  Terminal 1: cd $SCRIPT_DIR/backend && source venv/bin/activate && python main.py"
        echo "  Terminal 2: cd $SCRIPT_DIR/frontend && npm start"
        ;;
    docker)
        run_docker
        ;;
    docker-logs)
        cd "$SCRIPT_DIR"
        docker-compose logs -f
        ;;
    docker-stop)
        cd "$SCRIPT_DIR"
        docker-compose down
        echo -e "${GREEN}Docker containers stopped${NC}"
        ;;
    backend-setup)
        setup_backend
        ;;
    frontend-setup)
        setup_frontend
        ;;
    backend-run)
        run_backend
        ;;
    frontend-run)
        run_frontend
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo "Unknown command: $1"
        show_help
        exit 1
        ;;
esac
