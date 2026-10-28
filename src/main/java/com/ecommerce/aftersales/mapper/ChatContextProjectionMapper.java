package com.ecommerce.aftersales.mapper;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.Map;

@Mapper
public interface ChatContextProjectionMapper {

    @Select("SELECT session_id, last_message_id, goal_message_id, goal_text, goal_status "
            + "FROM chat_context_projection WHERE session_id = #{sessionId}")
    Map<String, Object> find(@Param("sessionId") Long sessionId);

    @Insert("INSERT INTO chat_context_projection "
            + "(session_id, last_message_id, goal_message_id, goal_text, goal_status) "
            + "VALUES (#{sessionId}, #{messageId}, #{goalMessageId}, #{goalText}, #{goalStatus}) "
            + "ON DUPLICATE KEY UPDATE "
            + "goal_message_id = IF(VALUES(last_message_id) > last_message_id, VALUES(goal_message_id), goal_message_id), "
            + "goal_text = IF(VALUES(last_message_id) > last_message_id, VALUES(goal_text), goal_text), "
            + "goal_status = IF(VALUES(last_message_id) > last_message_id, VALUES(goal_status), goal_status), "
            + "last_message_id = GREATEST(last_message_id, VALUES(last_message_id))")
    int saveIfNewer(@Param("sessionId") Long sessionId, @Param("messageId") Long messageId,
                    @Param("goalMessageId") Long goalMessageId, @Param("goalText") String goalText,
                    @Param("goalStatus") String goalStatus);
}
