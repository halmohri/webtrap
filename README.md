# webtrap
An online decoy defense for web endpoints. 

# Components
WebTrap includes a sample server application under
the server directory that exposes simulated endpoints. 
The main defense component is under the backend 
directory. The defense can run with detection only,
mitigation, and no canary options. 
A configuration file is expected for a successful run. 

# Requirements
Flask, Locust, psutil, SQLite

# Ideal execution environment
Ideally, run this with at least two gunicorn workers
and four threads on at least two CPUs. 