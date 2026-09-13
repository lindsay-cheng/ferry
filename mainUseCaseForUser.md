Dev A:
1. Finished working on branch x - someone else will take over. Code is pushed to github and merged into whichever branch
  a. Dev A can push his agent context 
2. Lets say that Dev A have a claude agent that is doing something on branch x - ie understands the project details end to end - instead of having to explain the feature/project to my teammate and having them re-explain to their agent we can transfer the context
  a. It could also be a small feature that they have implemented that dev B also needs for whatever reason
  b. This means that this is more efficient than teammate explaining project/using a md file that covers prd

Dev B:
1. Wants to continue working on branch x - pick up where dev a left - the code can be merged as normal but what we want is the agent context that dev a was working on
  a. Dev B pulls the agent context → now they can either fork the agent context and they have a fresh new agent with the context from dev A agent
  b. Dev B already has a claude agent that they’ve used atm but they want to pull agent context and merge it into their current agent 
2. Dev B is working on branch y
  a. They want to merge the context into their agent so either fork it or do an educated merge - ie. they want the model to know the project end to end already
