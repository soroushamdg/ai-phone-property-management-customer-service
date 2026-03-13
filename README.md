# AI Phone Property Management System

An intelligent phone-based property management assistant powered by OpenAI's real-time API and Twilio. The system provides natural voice conversations for rental property inquiries, customer support, and ticket management.

## 🚀 Features

### 📞 **Voice Intelligence**
- **Real-time voice conversations** using OpenAI's GPT-4o real-time preview
- **Natural speech processing** with server-side voice activity detection
- **Contextual responses** with customer history and preferences
- **Smart call ending** - detects when goodbye message completes before hanging up

### 🏠 **Property Management**
- **Knowledge base integration** with Montreal rental properties
- **Semantic property search** using ChromaDB vector embeddings
- **Proactive suggestions** based on user preferences
- **Detailed property information** including amenities, locations, and pricing

### 🎫 **Customer Support**
- **Contact management** with phone number recognition
- **Support ticket system** with categories and status tracking
- **Customer history** - AI remembers previous interactions
- **Personalized greetings** for returning customers

### 🛠 **Developer Tools**
- **Ngrok integration** for easy local development
- **Environment-based configuration** with `.env` support
- **Modular architecture** with separate database and knowledge base modules
- **Comprehensive error handling** and logging

## 📋 System Requirements

- Python 3.8+
- Twilio account (for phone numbers and voice handling)
- OpenAI API key (with GPT-4o real-time access)
- Supabase account (for database hosting)
- Ngrok (for local development tunneling)

## 🛠 Installation

### 1. **Clone the Repository**
```bash
git clone <repository-url>
cd phoneagent
```

### 2. **Create Virtual Environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. **Install Dependencies**
```bash
pip install -r requirements.txt
```

### 4. **Environment Configuration**
Copy the example environment file:
```bash
cp .env.example .env
```

Edit `.env` with your configuration:
```env
# OpenAI Configuration
OPENAI_API_KEY=sk-your-openai-api-key

# Supabase Database
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-anon-key

# Server Configuration
PORT=8000

# Knowledge Base (Optional)
ENABLE_KNOWLEDGE_BASE=true
```

### 5. **Database Setup**
Create the required tables in your Supabase project:

```sql
-- Contacts Table
CREATE TABLE contacts (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name TEXT NOT NULL,
    phone_number TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Tickets Table
CREATE TABLE tickets (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    contact_id UUID REFERENCES contacts(id),
    description TEXT NOT NULL,
    category TEXT CHECK (category IN ('issue', 'request', 'general')),
    status TEXT DEFAULT 'to_do' CHECK (status IN ('to_do', 'in_progress', 'done')),
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 6. **Knowledge Base Setup** (Optional)
If enabling the knowledge base, add property information to the `knowledge_base/` directory:

```bash
knowledge_base/
├── properties_griffintown_sud_ouest.md
├── properties_lasalle_outer_districts.md
├── properties_ville_marie_old_mtl.md
└── mock_questions.txt
```

Each markdown file should follow this format:
```markdown
# Neighborhood Name

## Property Name
* **Address:** 123 Street Name, Montreal, QC
* **Neighborhood:** Neighborhood Name
* **Unit Types:** Studio, 1, 2, 3 Bedrooms
* **Utilities Included:** Heating, Electricity, Hot Water
* **Amenities:**
    * Pool, gym, rooftop terrace
    * Coworking space, lounge
* **Description:** Brief property description
* **Source:** [property-website.com](https://example.com)
```

## 🚀 Running the Application

### **Easy Start (Recommended)**
Use the provided run script:
```bash
chmod +x run
./run
```

This script will:
- ✅ Activate virtual environment
- ✅ Pull latest code changes
- ✅ Install/update dependencies
- ✅ Start Ngrok tunnel
- ✅ Display public URL for Twilio webhook
- ✅ Launch the main application

### **Manual Start**
If you prefer manual setup:

1. **Start Ngrok** (in separate terminal):
```bash
ngrok http 8000
```

2. **Update Twilio Webhook**:
   - Go to your Twilio phone number settings
   - Set webhook URL to: `https://your-ngrok-url.ngrok.io/incoming-call`
   - Set HTTP method to POST

3. **Start Application**:
```bash
source venv/bin/activate
python main.py
```

## 📱 How It Works

### **Call Flow**
1. **Incoming Call** → Twilio receives call
2. **Webhook Trigger** → Twilio sends to `/incoming-call`
3. **TwiML Response** → Connects to WebSocket stream
4. **AI Session** → OpenAI real-time connection established
5. **Customer Recognition** → Looks up phone number in database
6. **Personalized Greeting** → AI greets customer by name (if known)
7. **Conversation** → AI assists with properties or support
8. **Smart Call End** → AI says goodbye, system detects completion

### **AI Capabilities**

#### **Property Management Mode** (Knowledge Base Enabled)
- Search properties by location, amenities, or features
- Provide detailed property information
- Make proactive suggestions based on preferences
- Compare neighborhoods and properties
- Load complete knowledge base for comprehensive answers

#### **General Support Mode** (Knowledge Base Disabled)
- Handle customer service inquiries
- Create and manage support tickets
- Register new customers
- Provide general assistance

#### **Available Tools**
- `search_properties(query)` - Semantic property search
- `load_knowledge_base()` - Load all property information
- `register_user(name)` - Register new customer
- `create_ticket(description, category)` - Create support ticket
- `end_call()` - End conversation politely

## 🔧 Configuration Options

### **Environment Variables**
```env
# Required
OPENAI_API_KEY=sk-...                    # OpenAI API key
SUPABASE_URL=https://...supabase.co      # Supabase project URL
SUPABASE_KEY=...                         # Supabase anon key

# Optional
PORT=8000                                # Server port (default: 8000)
ENABLE_KNOWLEDGE_BASE=true               # Enable property management features
```

### **System Prompts**
The system uses different prompts based on configuration:

- **Knowledge Base Enabled**: Property management assistant
- **Knowledge Base Disabled**: General customer support

## 🐛 Troubleshooting

### **Common Issues**

#### **"Name or service not known" Error**
- **Cause**: Invalid Supabase URL in `.env` file
- **Fix**: Update `SUPABASE_URL` with correct project URL from Supabase dashboard

#### **ChromaDB Initialization Issues**
- **Cause**: Missing sentence-transformers or dependency conflicts
- **Fix**: `pip install --upgrade sentence-transformers huggingface_hub`

#### **Twilio Connection Issues**
- **Cause**: Ngrok tunnel not running or webhook URL incorrect
- **Fix**: Ensure Ngrok is running and webhook URL is updated in Twilio

#### **OpenAI API Errors**
- **Cause**: Invalid API key or insufficient permissions
- **Fix**: Verify API key has GPT-4o real-time access

### **Debug Mode**
For debugging, you can test individual components:

```bash
# Test database connection
python -c "import db; print(db.get_contact('test'))"

# Test knowledge base
python -c "import knowledge_base; print(knowledge_base.get_all_knowledge())"

# Test OpenAI connection
python test_websocket.py  # Create this test file
```

## 📁 Project Structure

```
phoneagent/
├── main.py                 # Main FastAPI application
├── db.py                   # Supabase database operations
├── knowledge_base.py       # ChromaDB knowledge base system
├── requirements.txt        # Python dependencies
├── .env.example           # Environment template
├── .gitignore             # Git ignore rules
├── run                    # Deployment script
├── README.md              # This file
└── knowledge_base/        # Property information files
    ├── properties_*.md    # Property listings by area
    └── mock_questions.txt # Sample customer queries
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License.

## 🆘 Support

For issues and questions:
- Check the troubleshooting section above
- Review the debug commands
- Open an issue on GitHub

---

**Built with ❤️ using OpenAI, Twilio, Supabase, and ChromaDB**
