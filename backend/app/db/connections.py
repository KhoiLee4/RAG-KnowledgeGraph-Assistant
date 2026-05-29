import chromadb
from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

load_dotenv()

def test_chroma():
    client = chromadb.HttpClient(host="localhost", port=8000)
    print("ChromaDB connected:", client.heartbeat())

def test_neo4j():
    driver = GraphDatabase.driver(
        "bolt://localhost:7687",
        auth=("neo4j", "yourpassword")
    )
    driver.verify_connectivity()
    print("Neo4j connected!")
    driver.close()

if __name__ == "__main__":
    test_chroma()
    test_neo4j()