# SWOT Dashboard - Streamlit Cloud Deployment Guide

**Status**: Ready for deployment
**Target Platform**: Streamlit Community Cloud (Free Tier)
**Estimated Time**: 15-20 minutes

---

## 🎯 **What Changed**

### Performance Optimizations Applied:
✅ **Added caching** for expensive detrending calculations (`@st.cache_data`)
✅ **Limited baseline queries** to 50k points (prevents memory overflow)
✅ **Added memory management** (garbage collection after large operations)
✅ **Optimized database connection** with memory limits for DuckDB
✅ **Created Streamlit config** (`.streamlit/config.toml`) for performance tuning
✅ **Better error handling** with user-friendly messages

### Git LFS Configuration:
✅ **Created `.gitattributes`** for LFS tracking
✅ **Updated `.gitignore`** to allow parquet partition files
✅ **Data size**: 162.5 MB (68 partition files) - well within 1GB LFS limit

---

## 📋 **Prerequisites**

- [x] GitHub account (for repository hosting)
- [x] Streamlit Cloud account (free at https://streamlit.io/cloud)
- [ ] Git LFS installed on your system

---

## 🚀 **Deployment Steps**

### Step 1: Install Git LFS

Run this command in your terminal:

```bash
sudo apt-get update && sudo apt-get install -y git-lfs
```

Verify installation:

```bash
git lfs version
# Should output: git-lfs/3.x.x (GitHub; linux amd64; go 1.xx.x)
```

### Step 2: Initialize Git LFS in Your Repository

```bash
cd /home/luke/University/SWOT

# Initialize Git LFS
git lfs install

# Verify .gitattributes was recognized
git lfs track
# Should show: batch_outputs/master_all_data_part_*.parquet
```

### Step 3: Test Dashboard Locally (Recommended)

Before deploying, test the optimized dashboard:

```bash
# Install/update requirements
pip install -r requirements.txt

# Run dashboard locally
streamlit run dashboard_lugia.py

# Open browser to http://localhost:8501
# Test all tabs and verify no crashes
# Monitor terminal for any errors
```

**Testing Checklist:**
- [ ] Dashboard loads without errors
- [ ] Both rivers selectable
- [ ] All 6 tabs work (Gradient, Elevation Diff, Detrended, Interval Slopes, Map, Raw Data)
- [ ] Switching detrending methods works smoothly
- [ ] Map renders without lag
- [ ] Form prevents infinite reruns

### Step 4: Stage and Commit Parquet Files with Git LFS

```bash
# Check status (you should see optimizations + new files)
git status

# Add the batch_outputs directory (LFS will handle parquet files)
git add batch_outputs/master_all_data_part_*.parquet

# Verify Git LFS is tracking them (should show pointer files, not full files)
git lfs ls-files
# Should list all partition files

# Add other changes (optimizations, configs, docs)
git add dashboard_lugia.py
git add .streamlit/config.toml
git add .gitignore
git add .gitattributes
git add dashboard_optimizations.md
git add DEPLOYMENT.md

# Commit with descriptive message
git commit -m "$(cat <<'EOF'
Optimize dashboard for Streamlit Cloud deployment

Performance Improvements:
- Add caching for detrending calculations (@st.cache_data)
- Limit baseline queries to 50k points (memory safety)
- Add garbage collection after large operations
- Set DuckDB memory limit to 800MB
- Create .streamlit/config.toml for performance tuning
- Improve error handling with user-friendly messages

Git LFS Setup:
- Configure Git LFS for parquet partition files (162.5 MB)
- Update .gitignore to allow partition files through LFS
- Create .gitattributes for LFS tracking

Deployment Readiness:
- Add comprehensive deployment documentation
- Create optimization report with crash analysis
- Backup original dashboard as dashboard_lugia.py.backup

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
EOF
)"
```

### Step 5: Push to GitHub

```bash
# Push to GitHub (this will upload LFS files)
git push origin main

# This may take 2-5 minutes depending on your internet speed
# Git LFS will show upload progress for parquet files
```

**Expected Output:**
```
Uploading LFS objects: 100% (68/68), 162 MB | 5 MB/s, done.
```

### Step 6: Deploy to Streamlit Cloud

1. **Go to**: https://streamlit.io/cloud
2. **Sign in** with GitHub
3. **Click**: "New app"
4. **Configure**:
   - **Repository**: `lukestork839/SWOT_Dashboard`
   - **Branch**: `main`
   - **Main file path**: `dashboard_lugia.py`
5. **Advanced settings** (optional):
   - Python version: `3.11` (recommended)
6. **Click**: "Deploy!"

**Deployment time**: 5-10 minutes (includes installing dependencies + loading data)

### Step 7: Monitor Deployment

Watch the deployment logs:
- ✅ **"Installing requirements"** - Should see all packages installing
- ✅ **"Building app"** - Dashboard initializing
- ✅ **"Running"** - Success! 🎉
- ❌ **If errors occur** - See Troubleshooting section below

### Step 8: Test Live Dashboard

Once deployed, test thoroughly:
- [ ] Dashboard loads (may take 10-15 seconds on first load)
- [ ] Data displays correctly
- [ ] All tabs functional
- [ ] No crashes when switching parameters
- [ ] Map rendering works
- [ ] Detrending calculations complete without timeout

---

## 🐛 **Troubleshooting**

### Issue: "Module not found" error
**Solution**: Check `requirements.txt` is up to date
```bash
pip freeze | grep -E "(streamlit|duckdb|plotly|folium)" > requirements_check.txt
```

### Issue: "File not found: batch_outputs/"
**Solution**: Git LFS files didn't upload correctly
```bash
# Re-push LFS files
git lfs push --all origin main
```

### Issue: Dashboard loads but shows "No data found"
**Solution**: Verify parquet files were tracked by LFS
```bash
# Check LFS status
git lfs ls-files

# Should show all partition files
# If empty, re-track and re-commit:
git lfs track "batch_outputs/master_all_data_part_*.parquet"
git add .gitattributes
git add batch_outputs/master_all_data_part_*.parquet --force
git commit -m "Re-add parquet files to Git LFS"
git push origin main
```

### Issue: Memory error / App crash
**Symptoms**: Dashboard crashes when selecting both rivers or switching detrending methods

**Solution**: Verify optimizations are in place
```bash
# Check if gc import exists
grep "import gc" dashboard_lugia.py

# Check if MAX_BASELINE_POINTS is set
grep "MAX_BASELINE_POINTS" dashboard_lugia.py

# Check if caching decorator exists
grep "@st.cache_data" dashboard_lugia.py
```

If missing, dashboard wasn't updated correctly. Re-apply from backup:
```bash
# Compare with backup
diff dashboard_lugia.py dashboard_lugia.py.backup
```

### Issue: "Repository too large" error
**Solution**: You're pushing the wrong files (CSVs instead of just parquets)
```bash
# Check what's being tracked
git ls-files batch_outputs/

# Should ONLY show parquet partition files
# If you see CSVs or master_all_data.parquet, they weren't gitignored correctly
```

### Issue: Streamlit Cloud "Resource Limit Exceeded"
**Symptoms**: Dashboard works locally but crashes on Streamlit Cloud

**Solutions**:
1. **Reduce MAX_BASELINE_POINTS** (currently 50k):
   ```python
   MAX_BASELINE_POINTS = 30000  # More conservative
   ```

2. **Enable aggressive caching**:
   ```python
   @st.cache_data(ttl=7200)  # Cache for 2 hours
   ```

3. **Reduce MAX_PLOT_POINTS**:
   ```python
   MAX_PLOT_POINTS = 15000  # From 25000
   ```

### Issue: App "Sleeping" or "Booting"
**This is normal!** Streamlit Cloud free tier apps sleep after inactivity.
- First load after sleep: 30-60 seconds
- Subsequent loads: <5 seconds

---

## 📊 **Performance Expectations**

### Streamlit Cloud (Free Tier) Performance:

| Metric | Expected Performance |
|--------|---------------------|
| **First Load** | 30-60 seconds (waking from sleep) |
| **Subsequent Loads** | 3-5 seconds |
| **Tab Switching** | <1 second (instant) |
| **Detrending Calc** | 1-3 seconds (first time), <0.1s (cached) |
| **Map Rendering** | 2-4 seconds (10k points) |
| **Form Submit** | 2-5 seconds (full recalculation) |
| **Memory Usage** | ~500-700 MB (well under 1GB limit) |
| **Crash Rate** | Near zero (if optimizations applied) |

### Known Limitations on Free Tier:

⚠️ **Resource Limits**:
- 1 GB RAM
- Shared CPU
- 1 GB Git LFS storage
- App sleeps after 7 days inactivity

⚠️ **Not Recommended**:
- Uploading new data through UI (use Git push instead)
- Running Lugia.py on Streamlit Cloud (too expensive)
- Serving 10+ concurrent users (consider paid tier)

---

## 🔐 **Security & Privacy**

### Current Setup:
- ✅ **Public dashboard** - Anyone with URL can access
- ✅ **No sensitive data** - Only processed SWOT satellite data (public domain)
- ✅ **No authentication** - Open access for scientific collaboration

### Optional: Add Authentication

If you want to restrict access:

1. **Add secrets** in Streamlit Cloud dashboard:
   ```toml
   # .streamlit/secrets.toml (not in Git)
   password = "your-secure-password"
   ```

2. **Add authentication to dashboard**:
   ```python
   import streamlit as st

   def check_password():
       """Returns True if password is correct"""
       def password_entered():
           if st.session_state["password"] == st.secrets["password"]:
               st.session_state["password_correct"] = True
               del st.session_state["password"]
           else:
               st.session_state["password_correct"] = False

       if "password_correct" not in st.session_state:
           st.text_input("Password", type="password", on_change=password_entered, key="password")
           return False
       elif not st.session_state["password_correct"]:
           st.text_input("Password", type="password", on_change=password_entered, key="password")
           st.error("Password incorrect")
           return False
       else:
           return True

   if not check_password():
       st.stop()
   ```

---

## 🔄 **Updating Your Deployed Dashboard**

After deployment, you can update the dashboard by:

1. **Make changes locally**
2. **Test with** `streamlit run dashboard_lugia.py`
3. **Commit and push to GitHub**:
   ```bash
   git add <changed-files>
   git commit -m "Update: description of changes"
   git push origin main
   ```
4. **Streamlit Cloud auto-deploys** (takes 2-3 minutes)

**No manual redeployment needed!** 🎉

---

## 📞 **Support & Resources**

### Streamlit Documentation:
- Cloud Deployment: https://docs.streamlit.io/streamlit-community-cloud
- Caching Guide: https://docs.streamlit.io/library/advanced-features/caching
- Configuration: https://docs.streamlit.io/library/advanced-features/configuration

### Git LFS Documentation:
- Tutorial: https://git-lfs.github.com/
- GitHub Integration: https://docs.github.com/en/repositories/working-with-files/managing-large-files

### SWOT Project Documentation:
- Technical Notes: `Claude/Claude_notes.md`
- README: `README.md`
- Optimization Report: `dashboard_optimizations.md`

### Troubleshooting:
- GitHub Issues: https://github.com/lukestork839/SWOT_Dashboard/issues
- Streamlit Community: https://discuss.streamlit.io/

---

## ✅ **Post-Deployment Checklist**

After successful deployment:

- [ ] Save the deployed URL (e.g., `https://your-app.streamlit.app`)
- [ ] Test on different browsers (Chrome, Firefox, Safari)
- [ ] Test on mobile device (responsive layout)
- [ ] Share with collaborators/professor
- [ ] Add URL to `README.md` and GitHub repo description
- [ ] Monitor usage and performance for first 24 hours
- [ ] Consider setting up uptime monitoring (optional)
- [ ] Update documentation with any issues encountered
- [ ] Plan regular data updates (re-run Lugia.py, push new parquets)

---

## 🎉 **Success!**

Your SWOT Dashboard should now be live and accessible to the world!

**Next Steps**:
1. Share the URL with your research team
2. Monitor performance for the first week
3. Iterate on any user feedback
4. Consider adding new features (authentication, exports, etc.)

---

**Last Updated**: 2026-02-23
**Author**: Luke Stork
**Optimization Assistance**: Claude Sonnet 4.5
