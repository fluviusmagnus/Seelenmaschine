# TODO

Bugs and improvements:

- [ ] 工具调用在context window中的位置存在错误
      如果一次请求返回
        aaa，toolcall，bbb
      实际组装为
        toolcall，aaa，bbb
      数据库中也是错的，只有及时发给telegram的消息是对的

- [ ] search_memories 工具
      应该设计一个默认为否的可选参数，决定搜索时是否包含当前对话。
      也加上session id，id包含到系统extra_context提示里去。

- [ ] 太多同步异步的代码重复了

