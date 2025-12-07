🚀 Apify Autonomous Agent
=========================

> **A Hackathon Project that builds its own tools.**_Powered by Model Context Protocol (MCP), Anthropic Claude, and Apify._

💡 What is it?
--------------

This is an **autonomous AI agent** capable of interacting with the real world through APIs and—crucially—**building its own tools when existing ones aren't enough.**

Unlike standard chatbots that are limited to pre-defined tools, this agent can:

1.  **Read & Process Emails**: It connects to Gmail, finds attachments (like PDF Rate Confirmations), reads them, and understands the context.
    
2.  **Take Action**: It drafts replies or contracts directly in your Gmail based on the document content.
    
3.  **Self-Expand**: If you ask it to scrape a website and no existing Apify Actor exists for the job, **it writes the Python code for a new Actor, deploys it to the Apify Cloud, makes it public, and immediately uses it to get your data.**
    

✨ Key Features
--------------

### 1\. 📧 Intelligent Gmail Processing

*   **PDF Parsing**: Automatically detects PDF attachments in emails (e.g., Invoices, Rate Confirmations).
    
*   **Context Extraction**: OCR-like capability to extract text from PDFs using pdfminer.
    
*   **Draft Automation**: Writes professional email drafts using the extracted context.
    

### 2\. 🏗️ Autonomous Actor Genesis (The "Killer Feature")

The agent isn't limited to a static toolkit.

*   **Search**: It first searches the Apify Store for existing tools.
    
*   **Build**: If no tool is found, it uses the **Apify CLI** to generate a new Python Actor from scratch.
    
*   **Deploy**: It pushes the code to the Apify platform and configures metadata (actor.json).
    
*   **Publish**: It switches the Actor to PUBLIC visibility automatically.
    
*   **Run**: It executes the brand-new tool immediately to solve your prompt.
    

### 3\. 🧠 Powered by MCP & Claude

*   Built on the **Model Context Protocol (MCP)** to standardize how the AI connects to local and remote resources.
    
*   Uses **Anthropic Claude 3.5 Sonnet** for high-level reasoning and code generation.
    

🛠️ Architecture
----------------

1.  **User Query**: You ask a question via the CLI.
    
2.  **MCP Client (Python)**: Manages the conversation history and tool routing.
    
3.  **Apify MCP Server**: Provides standard tools (search-actors, call-actor).
    
4.  **Local Tools**: Custom tools injected by the client (build\_apify\_actor, create\_gmail\_draft).
    
5.  **Execution**:
    
    *   **Cloud**: Scrapers run on Apify's infrastructure.
        
    *   **Local**: Actor building and Email processing happen securely on your machine.
        

🚀 Getting Started
------------------

### Prerequisites

*   **Python 3.11+**
    
*   **Node.js & npm** (for Apify CLI and MCP server)
    
*   **Apify Account** & API Token
    
*   **Anthropic API Key**
    
*   **Google Cloud Credentials** (client\_secret.json with Gmail scopes)
    

### Installation

1.  git clone \[https://github.com/yourusername/apify-autonomous-agent.git\](https://github.com/yourusername/apify-autonomous-agent.git)cd apify-autonomous-agent
    
2.  pip install -r requirements.txt# requirements includes: mcp, anthropic, apify-client, google-auth-oauthlib, google-api-python-client, pdfminer.six
    
3.  npm install -g apify-cliapify login
    
4.  ANTHROPIC\_API\_KEY=sk-ant-api03...APIFY\_TOKEN=apify\_api\_...
    
5.  python bin/scripts/token\_generator.pyThis authenticates you with Google and saves gmail\_credentials.json.
    

💻 Usage
--------

Run the client:

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   python bin/scripts/client.py   `

### Scenario A: The "Self-Building" Scraper

**Query:**

> _"I want to scrape the titles from https://news.ycombinator.com/ using BeautifulSoup, but I don't want to use an existing actor. Build a custom one for me."_

**What happens:**

1.  Agent writes main.py code for a new scraper.
    
2.  Agent runs apify create, apify push.
    
3.  Agent sets the new actor to **Public**.
    
4.  Agent runs the actor and returns the top 30 Hacker News titles.
    

### Scenario B: The "Logistics" Assistant

**Query:**

> _"gmail: subject:'Rate Confirmation'"(Agent finds the email, reads the attached PDF, and stores context)_

**Follow-up:**

> _"Create an email draft to boss@example.com with a contract summary based on that PDF."(Agent drafts a professional email in your Gmail drafts folder)_

📂 Project Structure
--------------------

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   ├── bin/  │   └── scripts/  │       ├── client.py           # The Brain: Main MCP Client & Tool Logic  │       ├── token_generator.py  # Auth: Gmail OAuth Helper  │       └── connet_mcp.py       # Util: Basic connection test  ├── gmail_processor/  │   ├── main.py                 # The Muscle: Gmail & PDF Processing Logic  │   └── gmail_credentials.json  # Generated credentials  └── generated_actors/           # Sandbox for auto-generated actors   `

🏆 Hackathon Context
--------------------

This project was built to demonstrate the power of **Agentic Workflows**. By giving an LLM the ability to **create software** (Actors) rather than just **use software**, we unlock infinite extensibility. The agent doesn't need to wait for a developer to add a new integration—it builds the integration itself.
