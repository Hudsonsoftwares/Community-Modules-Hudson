@echo off
REM ============================================================================
REM  build.bat — Build, tag, and push Odoo 18 Docker image to Docker Hub
REM
REM  Run from: C:\odoo-custom-addons\docker-deploy
REM
REM  IMPORTANT: Set your Docker Hub username below!
REM ============================================================================

REM ── CONFIGURATION ─────────────────────────────────────────────────────────
SET DOCKERHUB_USER=nandusaji
SET IMAGE_NAME=odoo18-custom
SET IMAGE_TAG=latest
SET FULL_IMAGE=%DOCKERHUB_USER%/%IMAGE_NAME%:%IMAGE_TAG%

echo.
echo ============================================================
echo   Odoo 18 Docker Image Builder + Push
echo ============================================================
echo.
echo   Docker Hub image: %FULL_IMAGE%
echo.


REM ── Step 1: Clean previous addons copy ────────────────────────────────────
if exist "addons" (
    echo [1/5] Cleaning previous addons copy...
    rmdir /S /Q "addons"
)

REM ── Step 2: Copy custom addons into the build context ─────────────────────
echo [2/5] Copying custom addons into build context...
mkdir "addons"

REM Copy each addon directory from C:\odoo-custom-addons
for %%D in (
    account-financial-reporting
    base_territory
    field-service
    helpdesk
    mis-builder
    partner-contact
    reporting-engine
    server-tools
    server-ux
    social
    stock-logistics-orderpoint
    web
    wms
) do (
    echo        Copying %%D ...
    xcopy /E /I /Q /Y "C:\odoo-custom-addons\%%D" "addons\%%D" >nul 2>&1
)

REM ── Step 3: Build the Docker image ────────────────────────────────────────
echo [3/5] Building Docker image: %IMAGE_NAME% ...
docker build -t %IMAGE_NAME% .
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Docker build failed!
    exit /b 1
)

REM ── Step 4: Tag the image ─────────────────────────────────────────────────
echo [4/5] Tagging image as %FULL_IMAGE% ...
docker tag %IMAGE_NAME% %FULL_IMAGE%

REM ── Step 5: Push to Docker Hub ────────────────────────────────────────────
echo [5/5] Pushing to Docker Hub...
docker push %FULL_IMAGE%
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Docker push failed! Make sure you are logged in:
    echo         docker login
    exit /b 1
)

echo.
echo ============================================================
echo   SUCCESS! Image pushed to Docker Hub.
echo ============================================================
echo.
echo   Image:        %FULL_IMAGE%
echo.
echo   Local test:   docker compose up -d
echo                 then visit http://localhost:8069
echo.
echo   Render:       Go to Render dashboard and trigger a
echo                 manual deploy, or it will auto-detect.
echo.
