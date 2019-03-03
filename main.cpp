#include <iostream>
#include <ctime>
#include <vector> 
#include <string>

using namespace std;
// Transaction data

struct TransactionData
{
	double amount;
	string senderKey;
	string recieverKey;
	time_t timestamp;
};

// Block class

class Block {
	private:
		int index;
		size_t blockHash;
		size_t previousHash;
		size_t generateHash();
	public:
		// Constructor
		Block(int idx, TransactionData d, size_t prevHash);
		// Get Original Hash
		size_t getHash();
		// Get Previous Hash
		size_t getPreviousHash();
		// Transaction data
		TransactionData data;
		// Validate Hash
		bool isHashValid();
};

//  Constructor with param
Block::Block(int idx, TransactionData d, size_t prevHash)
{
	index = idx;
	data = d;
	previousHash = prevHash;
	blockHash = generateHash();
}
// Private functions
size_t Block::generateHash()
{
	hash<string> hash1;
	hash<size_t> hash2;
	hash<size_t> finalHash;
	string toHash = to_string(data.amount) + data.recieverKey + data.senderKey + to_string(data.timestamp);
	return finalHash(hash1(toHash) + hash2(previousHash));
}
// Public funtion
size_t Block::getHash()
{
	return blockHash;
}
size_t Block::getPreviousHash()
{
	return previousHash;
}
bool Block::isHashValid()
{
	return generateHash() == blockHash;
}

// Block chain
class blockChain
{
	private:
		Block createGenesisBlock();
	public:
		vector<Block> chain;
		// Constructor 
		blockChain();
		// Public funtion
		void addBlock(TransactionData data);
		bool isChainValid();

		Block *getLatestBlock();
};
// Block Chain constructor
blockChain::blockChain()
{
	Block genesis = createGenesisBlock();
	chain.push_back(genesis);
}
Block blockChain::createGenesisBlock() {
	time_t current;
	TransactionData d;
	d.amount = 0;
	d.recieverKey = "None";
	d.senderKey = "None";
	d.timestamp = time(&current);
	hash<int> hash1;
	Block genesis(0, d, hash1(0));
	return genesis;
}
Block *blockChain::getLatestBlock()
{
	return  &chain.back();
}
void blockChain::addBlock(TransactionData d)
{
	int index = (int)chain.size();
	Block newBlock(index, d, getLatestBlock()->getHash());
}
bool blockChain::isChainValid()
{
	vector<Block>::iterator it;
	int chainLen = (int)chain.size();
	for(it=chain.begin(); it != chain.end(); it++)
	{
			Block currentBlock = *it;
			if(!currentBlock.isHashValid())
			{
				return false;
			}
			if(chainLen > 1){
				Block previousBlock =  *(it-1);
				if(currentBlock.getPreviousHash() != previousBlock.getHash())
				{
						return false;
				}
			}
	}
	return true;
}

int main()
{
	blockChain demoBlockChain;
	TransactionData data1;
	time_t data1Time;
	data1.amount = 1.5;
	data1.recieverKey = "Joe";
	data1.senderKey = "Hart";
	data1.timestamp = time(&data1Time);
	demoBlockChain.addBlock(data1);

	TransactionData data2;
	time_t data2Time;
	data2.amount = 2.5;
	data2.recieverKey = "John";
	data2.senderKey = "Bill";
	data2.timestamp = time(&data2Time);
	demoBlockChain.addBlock(data2);

	cout << "Is chain valid?" << endl << demoBlockChain.isChainValid() << endl;
	// Modify data
	Block *latestBlock = demoBlockChain.getLatestBlock();
	latestBlock->data.amount =  10000;
	cout << "Is chain still valid?" << endl << demoBlockChain.isChainValid() << endl;
	return 0;
}