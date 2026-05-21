#!/bin/bash

# Automated GitHub push for trading-dashboard

set -e

echo "🔄 Trading Dashboard → GitHub Push"
echo "=================================="
echo ""

# Check if git is installed
if ! command -v git &> /dev/null; then
    echo "❌ Git not installed. Install with: sudo apt install git"
    exit 1
fi

# Get repo URL
read -p "Enter your GitHub repo URL (https://github.com/USERNAME/trading-dashboard.git): " REPO_URL

# Verify repo URL format
if [[ ! $REPO_URL =~ ^https://github.com/.*\.git$ ]]; then
    echo "❌ Invalid repo URL format. Should be: https://github.com/USERNAME/REPO.git"
    exit 1
fi

echo ""
echo "📝 Configuring Git..."

# Configure git if not already done
if ! git config user.email &>/dev/null; then
    read -p "Enter your name: " USER_NAME
    read -p "Enter your email: " USER_EMAIL
    git config --global user.name "$USER_NAME"
    git config --global user.email "$USER_EMAIL"
    echo "✓ Git configured"
else
    echo "✓ Git already configured"
fi

echo ""
echo "🚀 Initializing repository..."

# Initialize git
if [ ! -d .git ]; then
    git init
    git remote add origin "$REPO_URL"
    echo "✓ Repository initialized"
else
    echo "✓ Git repository already exists"
    # Update remote if needed
    git remote set-url origin "$REPO_URL"
    echo "✓ Remote URL updated"
fi

echo ""
echo "📦 Staging files..."

# Add all files
git add .

# Count staged files
STAGED_COUNT=$(git status --short | wc -l)
echo "✓ Staged $STAGED_COUNT files"

echo ""
echo "💾 Creating commit..."

# Create commit if there are changes
if git diff --cached --quiet; then
    echo "⚠️  No changes to commit. Repository already up-to-date."
else
    git commit -m "Trading dashboard: production FastAPI + React + Finnhub integration"
    echo "✓ Commit created"
fi

echo ""
echo "🌿 Setting main branch..."

# Ensure main branch
git branch -M main 2>/dev/null || true
echo "✓ Branch: main"

echo ""
echo "📤 Pushing to GitHub..."

# Push to GitHub (with credentials prompt if needed)
if git push -u origin main --force-with-lease; then
    echo "✓ Successfully pushed to GitHub"
else
    echo "⚠️  Push failed. Common reasons:"
    echo "  1. GitHub authentication: https://docs.github.com/en/github/authenticating-to-github/connecting-to-github-with-ssh"
    echo "  2. Repository doesn't exist: Create at https://github.com/new"
    echo "  3. SSH key not set up: ssh-keygen -t ed25519"
    exit 1
fi

echo ""
echo "=================================="
echo "✅ Done! Repository pushed to GitHub"
echo ""
echo "Next steps:"
echo "1. Go to: https://cloud.digitalocean.com/apps"
echo "2. Create App → GitHub → Select trading-dashboard"
echo "3. Configure services and environment variables"
echo "4. Deploy!"
echo ""
echo "📍 Your repo: $REPO_URL"
