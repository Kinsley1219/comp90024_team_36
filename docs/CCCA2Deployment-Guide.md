<style>
pre code {
  color: #666;
}
</style>

### 1. Cluster Setup and Check connect

After receiving the Kubernetes config file from a teammate, we first set
up the local environment to connect to the cluster.

1.  Install required tools

<!-- -->

    brew install kubectl
    brew install helm
    brew install fission-cli

1.  Configure kubeconfig

<!-- -->

    mkdir -p ~/.kube
    cp /path/to/config ~/.kube/config
    chmod 600 ~/.kube/config

1.  Check Kubernetes cluster connection

<!-- -->

    kubectl get nodes
    kubectl get svc

1.  Check Elasticsearch

<!-- -->

    kubectl get svc -n elastic
    kubectl get svc -A | grep -i elastic

<img src="/Users/k-yao/Desktop/CCCA2Node.png" style="width:85.0%" />

1.  Get Elasticsearch password ( is “elastic”)

<!-- -->

    kubectl get secret elasticsearch-es-elastic-user -n elastic \
    -o go-template='{{.data.elastic | base64decode}}'

1.  Check Fission ( Use 1.22 version)

<!-- -->

    fission version
    kubectl get all -n fission

1.  Create Fission Environment ( Use 3.9 version to avoid 3.7
    incompatibility issues)

<!-- -->

    fission env create \
      --name python39 \
      --builder fission/python-builder-3.9 \
      --image fission/python-env-3.9

### 2. Fission - Backend Data Pipeline

##### Prerequisites

-   Kubernetes cluster (MRC / NeCTAR)
-   kubectl configured
-   Fission CLI installed (Serverless Functions)
-   Elasticsearch deployed in K8s (Data storage & analytics)

### 2.1 BlueSky Harvester

The system continuously harvests BlueSky data related to Australia
(fuel, cost of living, etc.) and stores it in Elasticsearch for further
analysis.

##### I. Crawling Strategy

The Bluesky harvester uses a combination of historical crawling and
real-time incremental crawling.

-   The crawler logs in to the Bluesky API and selects a small batch of
    queries in each run.
-   Historical posts are collected using the `until` parameter.
    -   The crawler gradually moves backwards in time and stores the
        history cursor in Elasticsearch.
-   New posts are collected using the `since` parameter.
    -   Only posts newer than the last collected timestamp are fetched.
-   Raw posts are cleaned and converted into structured Elasticsearch
    documents.
-   The Bluesky post URI is used as the Elasticsearch document ID to
    prevent duplicate data.
-   Cursor states are stored in the `bluesky-cursors` index, while
    collected social media posts are stored in the shared `social-posts`
    index.
-   The post URI is used as the Elasticsearch document ID to avoid
    duplicate records when multiple crawlers write to the same index.

This design supports continuous real-time updates while gradually
completing historical data collection without exceeding the Fission
timeout.

##### II. Current Status

-   Successfully deployed as a Fission serverless function on
    Kubernetes.
-   Connected to Elasticsearch for automatic data storage.
-   Supports both historical backfill and real-time crawling.
-   Timer-based crawling runs automatically. The interval was changed
    from every 2 minutes to a longer interval to avoid Bluesky API rate
    limits.
-   Data is continuously written into the shared `social-posts` index.

##### III. Bluesky Dataset Fields

The processed Bluesky dataset contains both original post attributes and
additional analytical features generated during preprocessing.

<table>
<colgroup>
<col style="width: 33%" />
<col style="width: 33%" />
<col style="width: 33%" />
</colgroup>
<thead>
<tr>
<th>Field</th>
<th>Type</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td><code>url</code></td>
<td>string</td>
<td>Unique URI of the Bluesky post and Elasticsearch document ID</td>
</tr>
<tr>
<td><code>text</code></td>
<td>text</td>
<td>Main textual content of the post</td>
</tr>
<tr>
<td><code>author</code></td>
<td>string</td>
<td>Bluesky user handle</td>
</tr>
<tr>
<td><code>query</code></td>
<td>string</td>
<td>Search keyword used during crawling</td>
</tr>
<tr>
<td><code>created_at</code></td>
<td>datetime</td>
<td>Original post creation timestamp</td>
</tr>
<tr>
<td><code>date</code></td>
<td>date</td>
<td>Extracted date used for aggregation</td>
</tr>
<tr>
<td><code>platform</code></td>
<td>string</td>
<td>Source platform identifier (<code>bluesky</code>)</td>
</tr>
<tr>
<td><code>ingested_at</code></td>
<td>datetime</td>
<td>Elasticsearch ingestion timestamp</td>
</tr>
<tr>
<td><code>like</code></td>
<td>integer</td>
<td>Number of likes</td>
</tr>
<tr>
<td><code>reply</code></td>
<td>integer</td>
<td>Number of replies</td>
</tr>
<tr>
<td><code>repost</code></td>
<td>integer</td>
<td>Number of reposts</td>
</tr>
<tr>
<td><code>is_fuel</code></td>
<td>boolean</td>
<td>Fuel-topic indicator</td>
</tr>
<tr>
<td><code>is_cost</code></td>
<td>boolean</td>
<td>Cost-of-living topic indicator</td>
</tr>
<tr>
<td><code>is_au</code></td>
<td>boolean</td>
<td>Australia-related indicator</td>
</tr>
<tr>
<td><code>sentiment_score</code></td>
<td>float</td>
<td>VADER sentiment score</td>
</tr>
<tr>
<td><code>sentiment_label</code></td>
<td>string</td>
<td>Sentiment category</td>
</tr>
<tr>
<td><code>matched_location</code></td>
<td>string</td>
<td>Detected Australian region</td>
</tr>
</tbody>
</table>

Additional engineered features were generated during preprocessing to
support downstream analysis and dashboard visualisation.

<table>
<colgroup>
<col style="width: 50%" />
<col style="width: 50%" />
</colgroup>
<thead>
<tr>
<th>Engineered Feature</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td><code>sentiment_score</code></td>
<td>Continuous VADER compound sentiment score ranging from
<code>-1</code> to <code>1</code></td>
</tr>
<tr>
<td><code>sentiment_label</code></td>
<td>Sentiment category derived from the sentiment score
(<code>positive</code>, <code>neutral</code>,
<code>negative</code>)</td>
</tr>
<tr>
<td><code>matched_location</code></td>
<td>Australian state or region inferred using keyword-based location
matching</td>
</tr>
<tr>
<td><code>is_fuel</code></td>
<td>Boolean indicator showing whether the post is related to fuel or
petrol topics</td>
</tr>
<tr>
<td><code>is_cost</code></td>
<td>Boolean indicator showing whether the post is related to
cost-of-living topics</td>
</tr>
<tr>
<td><code>is_au</code></td>
<td>Boolean indicator showing whether the post is related to
Australia</td>
</tr>
</tbody>
</table>

##### IV. Deployment Steps

#### Step 1. Create Secret (Hidden)

(And also can create Configmap, but I didn’t use it.)

Optional: Check Secret Yaml

    kubectl get secret es-secret -o yaml

#### Step 2. Upload zip file

Before create new zip, Check or Delete existing zip code file.

    rm -f bluesky-harvester.zip

Then Upload zip file: (bluesky\_fission.py + requirements.txt)

    zip -r bluesky-harvester.zip \
      bluesky_harvester.py \
      bluesky_processor.py \
      bluesky_storager.py \
      requirements.txt

#### Step 3. Create Package

Before create new package, Check or Delete existing package.

    fission package list
    fission package delete --name bluesky-pkg

Then, Create Fission Package

    fission package create \
      --name bluesky-pkg \
      --env python39 \
      --sourcearchive bluesky-harvester.zip

Wait for a few seconds, Confirm Package Succeeded instead of Running.

#### Step 4. Create Function

Before create, Check OR Delete existing package.

    fission fn list
    fission fn delete --name bluesky-harvester

Then, Create Fission Function

    fission fn create \
      --name bluesky-harvester \
      --pkg bluesky-pkg \
      --env python39 \
      --entrypoint "bluesky_harvester.main" \
      --secret es-secret \
      --fntimeout 120

#### Step 5. Test Fission Function

    fission fn test --name bluesky-harvester --timeout 5m

Expected output: {“saved”:xxx,“status”:“ok”,“total”:xxx}. Then create a
timer to automatically capture:

#### Step 6. Create Timer

    fission timer create \
      --name bluesky-timer \
      --function bluesky-harvester \
      --cron "@every 2m"
    #OR --cron "*/2 * * * *"

Check:

    fission timer list
    fission fn logs --name bluesky-harvester (optional)

#### Step 7. Connect ElasticSearch

(Local for check output)

    kubectl port-forward -n elastic svc/elasticsearch-es-http 9200:9200

Expect Output:

    Forwarding from 127.0.0.1:9200 -> 9200
    Forwarding from [::1]:9200 -> 9200

**Open a new terminal window and check the status of the write to ES.**

##### 7.1 Reset Data / Cursor (Important for Testing)

1.  Reset cursor only (Recommended for testing)

<!-- -->

    curl -k -u elastic:elastic -X DELETE https://localhost:9200/bluesky-cursors

-   This resets the Bluesky crawler progress only. Existing post data in
    `social-posts` will remain.
-   Use this when you changed the code and want the crawler to re-run
    history crawling.

1.  Full reset from scratch

<!-- -->

    #(old verssion) curl -k -u elastic:elastic -X DELETE https://localhost:9200/bluesky-posts
    curl -k -u elastic:elastic -X DELETE https://localhost:9200/social-posts
    curl -k -u elastic:elastic -X DELETE https://localhost:9200/bluesky-cursors

-   This deletes both the stored data and the crawling progress.
-   Use this only when you want to start completely from zero.

#### Step 8. Check Data

Next time you reopen, just check:

    # The total number of data that have been collected and are being written to ES.
    curl -k -u elastic:elastic "https://localhost:9200/social-posts/_count"

    # Checks how many Bluesky records have been written into the shared social-posts index.
    curl -k -u elastic:elastic \ "https://localhost:9200/social-posts/_count?q=platform:bluesky"

Expected output:
{“count”:xxx,“\_shards”:{“total”:x,“successful”:x,“skipped”:x,“failed”:x}}.

#### Step 9. Overall Update Deployment

**If you modify the .py code file, you need to update zip, package,
function and re-run the test.**

    # 1. Repackage after modifying the code
    rm -f bluesky-harvester.zip
    zip -r bluesky-harvester.zip \
      bluesky_harvester.py \
      bluesky_processor.py \
      bluesky_storager.py \
      requirements.txt

    # 2. Update package
    fission package update \
      --name bluesky-pkg \
      --sourcearchive bluesky-harvester.zip
      
    # 3. Update function
    fission fn update \
      --name bluesky-harvester \
      --entrypoint "bluesky_harvester.main" \
      --secret es-secret \
      --fntimeout 120
      

    # Optional: Delete the old functions and packages
    fission timer delete --name bluesky-timer
    fission fn delete --name bluesky-harvester
    fission package delete --name bluesky-pkg

    # Create a new package
    fission package create \
      --name bluesky-pkg \
      --env python39 \
      --sourcearchive bluesky-harvester.zip

    # Rebuild the function and add a 120-second function timeout
    fission fn create \
      --name bluesky-harvester \
      --pkg bluesky-pkg \
      --env python39 \
      --entrypoint "bluesky_harvester.main" \
      --secret es-secret \
      --fntimeout 120

    # 4. Delete the entire Elasticsearch index (clear all data + reset crawler state)
    # old version : curl -k -u elastic:elastic -X DELETE https://localhost:9200/bluesky-posts
    curl -k -u elastic:elastic -X DELETE https://localhost:9200/social-posts
    curl -k -u elastic:elastic -X DELETE https://localhost:9200/bluesky-cursors

    # 5. Simple test. If there are no issues, then use timer
    time fission fn test --name bluesky-harvester --timeout 2m

    # 6. Create timer for automatic capture
    fission timer create \
      --name bluesky-timer \
      --function bluesky-harvester \
      --cron "@every 2m"

#### Step10. Generate Fission Specs (Optional)

Fission specs can be used to save deployment configurations into YAML
files for reproducible deployment.

    # i. Initialize Spec Directory
    rm -rf specs 
    fission spec init

    # ii. Generate Package Spec
    fission package create \
      --spec \
      --name bluesky-pkg \
      --env python39 \
      --sourcearchive bluesky-harvester.zip
      
    # iii. Generate Function Spec
    fission fn create \
      --spec \
      --name bluesky-harvester \
      --pkg bluesky-pkg \
      --env python39 \
      --entrypoint "bluesky_harvester.main" \
      --secret es-secret \
      --fntimeout 120
      
    # iv. Generate Timer Spec
    fission timer create \
      --spec \
      --name bluesky-timer \
      --function bluesky-harvester \
      --cron "@every 2m"

    # v. Apply Specs
    # Before applying specs, delete existing resources to avoid conflicts.
    fission timer delete --name bluesky-timer
    fission fn delete --name bluesky-harvester
    fission package delete --name bluesky-pkg

    # Then apply:
    fission spec apply

    # vi. Test Function
    time fission fn test --name bluesky-harvester --timeout 2m

#### IV. Issues & Fixes

During deployment, several issues were encountered:

-   Package stuck in `running` → caused by heavy dependencies such as
    `pandas`, which significantly slowed down Fission package builds.
-   Package failed → caused by Python version incompatibility with the
    default Fission Python 3.7 environment.
-   Function timeout → caused by attempting to crawl large amounts of
    historical data in a single execution.
-   Bluesky API `429 Too Many Requests` → caused by frequent login
    requests and short timer intervals.

Solutions:

-   Removed `pandas` from both the crawler logic and `requirements.txt`;
-   Switched to a Python 3.9 Fission environment;
-   Implemented incremental crawling with small query batches and cursor
    tracking;
-   -   Replaced the rate-limited Bluesky account and updated the
        Kubernetes secret credentials.

These improvements made the pipeline stable and compatible with Fission
serverless execution.

#### V. Index Update Note

The original Bluesky-only index was `bluesky-posts`. It was later
changed to the shared index `social-posts` so that Bluesky and Reddit
social media data can be stored under the same schema and queried
together in Kibana.

To support this shared index design:

-   all social media documents include a `platform` field, such as
    `bluesky` or `reddit`;
-   Bluesky records are queried with `platform:bluesky`;
-   Reddit records are queried with `platform:reddit`;
-   crawler progress is still stored separately in `bluesky-cursors`,
    because cursor state is only used by the Bluesky crawler.

### 2.2 Official FuelPrice Harvester

The system harvests historical retail fuel price data from the Western
Australia (WA) FuelWatch API. It focuses on the Unleaded Petrol (ULP)
time series to support cost-of-living and social media correlation
analysis.

##### i. Data Processing Logic

-   **Source**: Automated download of monthly retail fuel CSV reports
    from the FuelWatch WA API.
-   **Cleaning**: Filters raw data for `PRODUCT_DESCRIPTION == "ULP"` to
    isolate unleaded petrol records.
-   **Aggregation**: Computes daily average prices across all stations,
    reducing millions of raw records into a structured daily time
    series.
-   **Incremental Mode**: Uses a `MAX_FILES` constraint to process data
    in smaller batches, preventing Fission execution timeouts during the
    initial backfill.

##### ii. Deployment Steps (Hongkun Zhang’s work)

#### Step 1. Build and Package

Create the deployment archive for the FuelWatch pipeline.

    # Zip the script and requirements
    zip -r fuelwatch-harvester.zip \
      fuelwatch_fission.py \
      requirements.txt

#### Step 2. Create Fission Resources

Deploy the code as a serverless function

    # Create Fission Package
    fission package create \
      --name fuelwatch-pkg \
      --env python39 \
      --sourcearchive fuelwatch-harvester.zip

    # Create Fission Function
    fission fn create \
      --name fuelwatch-harvester \
      --pkg fuelwatch-pkg \
      --env python39 \
      --entrypoint "fuelwatch_fission.main" \
      --fntimeout 120

#### Step 3. Test and Execution

    # Test the function with an extended timeout
    fission fn test --name fuelwatch-harvester --timeout 3m

Expected output: {“status”: “ok”, “monthly\_files\_attempted”: 2,
“daily\_records”: xx, “saved”: xx}.

#### Step 4. Check Data in ElasticSearch

Verify that the aggregated time series data has been indexed
successfully.

    curl -k -u elastic:elastic "https://localhost:9200/fuelwatch-dev/_count"

Expected output:
{“count”:xxxx,“\_shards”:{“total”:x,“successful”:x,“skipped”:x,“failed”:x}}

#### III. Issues Encountered & Fixes

-   **Fission Environment Variable Limitation**:
    -   **Issue**: Attempting to pass `MAX_FILES` via the Fission CLI
        (`--env MAX_FILES=2`) failed to trigger correctly in the
        runtime.
    -   **Solution**: Switched to a hardcoded default value within the
        script and relied on local code logic for incremental ingestion
        control.
-   **Large Dataset Execution Timeout**:
    -   **Issue**: Processing 4.3 million raw records from the
        historical API exceeded the default Fission timeout, causing
        `request timeout` errors.
    -   **Solution**: Implemented **Incremental Ingestion** by limiting
        the function to process only 2 monthly files per run
        (`MAX_FILES = 2`) and extended the test timeout to 3 minutes
        (`--timeout 3m`).
-   **Storage Optimization**:
    -   **Issue**: High memory usage when processing full CSV files in a
        container.
    -   **Solution**: Performed pre-aggregation (computing daily
        averages) before writing to Elasticsearch, significantly
        reducing the indexing load and storage footprint.

### 3. Kibana Data Visualization

#### step 1: Connect Kibana

    kubectl port-forward svc/kibana-kb-http -n elastic 5601:5601

Expect Output:

    Forwarding from 127.0.0.1:5601 -> 5601
    Forwarding from [::1]:5601 -> 5601

**Open in your local browser: <https://localhost:5601>**

You can view the real-time captured data, will see table-like view of
the data (similar to Excel).

#### step 2: Login

    Username: elastic
    Password: elastic

#### step 3: Create Data View

Left side Navigate to:

    Stack Management → Data Views → Create data view

**Fill in to see Bluesky data:**

    Name: bluesky
    Index pattern: social-posts #(old version bluesky-posts)
    Time field: created_at # or ingested_at

**Fill in to see Fuel Prices data ( Hongkun’s work ):**

    Name: fuelwatch
    Index pattern: fuelwatch-*
    Time field: date

**Note:** Unlike BlueSky data which uses `created_at`, FuelWatch uses
the calculated `date` field from the daily price aggregation.

#### step 4: Explore Data

    For Social Media:  Discover → Select "bluesky"
    For Fuel Prices:   Discover → Select "fuelwatch"

### 4. GitLab Workflow for Bluesky Backend

#### Step1. Set up GitLab SSH access

Run the following commands to generate an SSH key and print the public
key:

    ssh-keygen -t ed25519 -C "UserName@student.unimelb.edu.au"

    Prompt to enter the password three times: `Press Enter`

    # Then print the public key:
    cat ~/.ssh/id_ed25519.pub

Copy output like:
`ssh-ed25519 XXXXX...XXXX UserName@student.unimelb.edu.au`

Add it to GitLab: `GitLab → Edit profile → SSH Keys → Add new key`

After adding the key, test the SSH connection:

    ssh -T git@gitlab.unimelb.edu.au

Expect successful connection: `Welcome to GitLab, @Username!` \####
Step1. Create local Git folder and clone repository

#### Step2. Clone repository

    mkdir -p ~/git
    cd ~/git
    git clone git@gitlab.unimelb.edu.au:JUNYAOZ5/comp90024_team_36.git

Enter the local repository:

    cd ~/Documents/COMP90024/cccAsm2/git/comp90024_team_36

    # Check the current branch
    git branch

#### Step3: Create new branch & Add files

    git checkout -b feature/bluesky

Create the backend folder:

    mkdir -p backend/bluesky

Copy the Bluesky Fission files into the Git repository:

    cp ~/Documents/COMP90024/cccAsm2/2.Fission\ Harvester/bluesky-harvester.zip backend/bluesky/
    cp ~/Documents/COMP90024/cccAsm2/2.Fission\ Harvester/requirements.txt backend/bluesky/
    cp ~/Documents/COMP90024/cccAsm2/2.Fission\ Harvester/bluesky_harvester.py backend/bluesky/
    cp ~/Documents/COMP90024/cccAsm2/2.Fission\ Harvester/bluesky_processor.py backend/bluesky/
    cp ~/Documents/COMP90024/cccAsm2/2.Fission\ Harvester/bluesky_storager.py backend/bluesky/
    cp -R ~/Documents/COMP90024/cccAsm2/2.Fission\ Harvester/specs backend/bluesky/

    # Check whether the files were copied successfully
    ls backend/bluesky
    ls backend/bluesky/specs

#### Step4. Commit and Push to GitLab

    # Stage all files
    git add backend/bluesky
    # Check the files before committing
    git status
    # Commit the changes
    git commit -m "Add Bluesky backend pipeline"
    git push origin feature/bluesky

#### Step5. Upload the R Markdown and HTML files

Enter the local Git repository:

    cd ~/Documents/COMP90024/cccAsm2/git/comp90024_team_36

Copy the `.Rmd` and `.html` files into the repository:

    cp ~/Documents/COMP90024/cccAsm2/CCCA2Deployment\ Guide.Rmd .
    cp ~/Documents/COMP90024/cccAsm2/CCCA2Deployment-Guide.html .

    ls

Stage and upload the files to GitLab:

    git add "CCCA2Deployment Guide.Rmd"
    git add CCCA2Deployment-Guide.html
    git status
    git commit -m "Add deployment guide report"
    git push

#### If Rename and Update Branch

Rename the local branch:

    # Rename the local branch:
    git branch -m feature/xinyao-bluesky
    # Push the renamed branch to GitLab:
    git push origin feature/xinyao-bluesky
    # Delete the old remote branch:
    git push origin --delete feature/bluesky
    # Set the upstream tracking branch:
    git push --set-upstream origin feature/xinyao-bluesky
    # Delete old branch:
    git push origin --delete feature/bluesky
    # Check the final branch:
    git branch

#### Step 6. Update Deployment Guide Files in GitLab

After modifying the `.Rmd` deployment guide locally, the updated `.Rmd`
and generated `.html` files were copied into the GitLab repository
`docs/` directory and pushed to GitLab.

Enter the local Git repository:

    cd "/Users/k-yao/Documents/COMP90024/cccAsm2/git/comp90024_team_36_clean"
    # Copy the updated files into docs/:
    cp ~/Documents/COMP90024/cccAsm2/CCCA2Deployment\ Guide.Rmd docs/
    cp ~/Documents/COMP90024/cccAsm2/CCCA2Deployment-Guide.html docs/
    # Check the updated files:
    ls docs
    # Stage, commit and push the updates:
    git add docs/
    git status
    git commit -m "Update deployment guide docs"
    git push

#### Step7. Re-clone Latest GitLab Repository

After merging the Bluesky backend into `main`, re-clone the latest
repository to keep the local project clean and synchronised with
teammates’ updates.

##### 1. Go to local git directory

    cd ~/Documents/COMP90024/cccAsm2/git

##### 2. Clone latest repository

    git clone git@gitlab.unimelb.edu.au:JUNYAOZ5/comp90024_team_36.git comp90024_team_36_clean

##### 3. Enter the new repository

    cd comp90024_team_36_clean

##### 4. Check branch

    git branch

Expected branch:

    main

##### 5. Pull latest updates

    git pull origin main

The latest repository should now contain:

    backend/fission/reddit
    backend/fission/bluesky

##### 6. Optional: Remove old local repository

After confirming the new repository works correctly:

    rm -rf ~/Documents/COMP90024/cccAsm2/git/comp90024_team_36

##### 7. Future update workflow

For future modifications:

    git checkout main
    git pull origin main
    git checkout -b feature/update-name

Modify files under:

    backend/fission/bluesky/

Then commit and push:

    git add .
    git commit -m "Update Bluesky backend"
    git push origin feature/update-name

Finally, create a new Merge Request:

    feature/update-name → main
